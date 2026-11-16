"""Builds the system prompt: generic rules + the application's own description (manifest, catalog,
profile primer) + the current situation, with application data fenced in <app_data>."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..contract import Scope, WyspError

if TYPE_CHECKING:
    from ..session.session import Session

PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"
MAX_FOCUS_ENTITIES = 20
MAX_FACT_BLOCK = 4000  # the adapter already bounds its context to 8 KB; this is a second guard
MAX_ENUM_SHOWN = 8


def _compact_schema(schema: dict) -> str:
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    parts = []
    for name, sub in props.items():
        t = sub.get("type", "any")
        enum = sub.get("enum")
        if enum and len(enum) > MAX_ENUM_SHOWN:  # keep the prompt small: free LLM tiers have tight token limits
            shown = "|".join(map(str, enum[:MAX_ENUM_SHOWN])) + f"|…(+{len(enum) - MAX_ENUM_SHOWN} more)"
        else:
            shown = "|".join(map(str, enum)) if enum else str(t)
        parts.append(f"{name}{'*' if name in required else ''}: {shown}")
    return "{" + ", ".join(parts) + "}"


async def build_system_prompt(session: Session) -> str:
    sections = [PROMPT_PATH.read_text(encoding="utf-8").strip(), f"Session language: {session.lang}."]
    conn = session.conn
    if conn is None:
        sections.append("No application is connected right now. Tell the user, and explain how to connect one.")
        return "\n\n".join(sections)

    m = conn.manifest
    kinds = "; ".join(f"{k.kind} = {k.label}" for k in m.entity_kinds)
    sections.append(
        f"# Application\n{m.app.name} {m.app.version}. Integration level: {m.integration_level}.\nEntity kinds: {kinds}.\n"
        f"Ref scheme: {m.ref_scheme}://"
    )
    if session.profile and session.profile.primer:
        sections.append(f"# About this application\n{session.profile.primer}")

    try:
        actions = await conn.get_actions()
    except WyspError:
        actions = []
    if actions:
        lines = [f"- {a.id} [{a.risk}]: {a.description} params {_compact_schema(a.params_schema)}" for a in actions]
        sections.append("# Action catalog (for propose_action)\n" + "\n".join(lines))

    data: list[str] = []
    try:
        ctx = await conn.get_context()
        data.append(f"Summary: {ctx.summary}")
        if ctx.mode:
            data.append(f"Mode: {ctx.mode}")
        if ctx.facts:
            # Long multi-line text facts (code, a selection) are shown whole in their own blocks: cutting the
            # JSON line at 600 characters used to hide them. Everything else stays on the short Facts line.
            blocks = {k: v for k, v in ctx.facts.items() if isinstance(v, str) and "\n" in v}
            short = {k: v for k, v in ctx.facts.items() if k not in blocks}
            data.append("Facts: " + json.dumps(short, ensure_ascii=False)[:600])
            for key, text in blocks.items():
                data.append(f"Fact {key} (verbatim, line numbers as in the file):\n{text[:MAX_FACT_BLOCK]}")
        if ctx.focus:
            data.append("Focus: " + ", ".join(ctx.focus))
    except WyspError as exc:
        data.append(f"(context unavailable: {exc.message})")
    await session.survey.wait()  # a survey in progress gets a few seconds; after that the turn goes on without it
    survey = session.survey.current
    if survey is not None and survey.status != "failed" and survey.adapter_id == conn.adapter_id:
        data.append(survey.render())
    if session.explorer.has_content():
        data.append(session.explorer.render())
    elif session.explorer.phase == "offer":
        data.append(
            "The project can be explored (a code map and a study of the main files), and the user has not agreed yet. "
            "The Panel offers it. Until they agree, you know only what the survey and your reads show: say so, and do "
            "not describe code you have not read."
        )
    try:
        obs = await session.observe(Scope(level="focus"))
        rows = []
        for e in obs.entities[:MAX_FOCUS_ENTITIES]:
            props = {k: v for k, v in e.props.items() if not isinstance(v, (dict, list)) and v is not None}
            rows.append(
                f"- {e.ref} [{e.kind}] {e.label} {json.dumps(dict(list(props.items())[:5]), ensure_ascii=False)}"
            )
        if rows:
            data.append("Entities near the focus:\n" + "\n".join(rows))
    except WyspError as exc:
        data.append(f"(observation unavailable: {exc.message})")
    if session.active_highlight is not None:
        data.append(
            f"Highlighted in the application now: {session.active_highlight.ref} "
            "(stays until the user interacts with it or you call clear_highlight)"
        )
    if session.board.nodes:
        data.append("On the board now: " + ", ".join(f"{n.label} ({n.provenance})" for n in session.board.nodes[:20]))
    sections.append("<app_data>\n" + "\n".join(data) + "\n</app_data>")
    return "\n\n".join(sections)
