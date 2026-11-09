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
MAX_FOCUS_ENTITIES = 25


def _compact_schema(schema: dict) -> str:
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    parts = []
    for name, sub in props.items():
        t = sub.get("type", "any")
        enum = sub.get("enum")
        desc = f"{name}{'*' if name in required else ''}: {'|'.join(map(str, enum)) if enum else t}"
        parts.append(desc)
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
            data.append("Facts: " + json.dumps(ctx.facts, ensure_ascii=False)[:600])
        if ctx.focus:
            data.append("Focus: " + ", ".join(ctx.focus))
    except WyspError as exc:
        data.append(f"(context unavailable: {exc.message})")
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
    if session.board.nodes:
        data.append("On the board now: " + ", ".join(f"{n.label} ({n.provenance})" for n in session.board.nodes[:20]))
    sections.append("<app_data>\n" + "\n".join(data) + "\n</app_data>")
    return "\n\n".join(sections)
