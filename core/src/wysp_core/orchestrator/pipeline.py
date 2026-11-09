"""Action pipeline: propose, validate, permission, execute, verify (or undo), evidence.

The LLM can only reach this code through the `propose_action` tool. Nothing here is skipped for
convenience: every executed action is verified, and failed reversible actions are undone.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

import jsonschema

from ..board import node_id
from ..contract import ActionCall, ActionSpec, Observation, WyspError
from ..trust import Proposal, UndoRecord
from ..verification import verify

if TYPE_CHECKING:
    from ..session.session import Session

log = logging.getLogger("wysp.pipeline")

TEMPLATE_RE = re.compile(r"\$\{(label:)?params\.([A-Za-z_][A-Za-z0-9_]*)\}")


def localized(text: Any, lang: str) -> str:
    if isinstance(text, dict):
        return str(text.get(lang) or text.get("en") or next(iter(text.values()), ""))
    return str(text)


def label_of(obs: Observation | None, ref: Any) -> str:
    if obs is not None and isinstance(ref, str):
        entity = obs.entity(ref)
        if entity is not None:
            return entity.label
    return str(ref)


def render_template(text: str, params: dict[str, Any], obs: Observation | None) -> str:
    def sub(m: re.Match) -> str:
        value = params.get(m.group(2), "")
        return label_of(obs, value) if m.group(1) else str(value)

    return TEMPLATE_RE.sub(sub, text)


def render_ref(target: str | None, params: dict[str, Any]) -> str | None:
    if not target:
        return None
    m = TEMPLATE_RE.fullmatch(target)
    if m and not m.group(1):
        value = params.get(m.group(2))
        return value if isinstance(value, str) else None
    return target


def target_label(spec: ActionSpec, params: dict[str, Any], obs: Observation | None) -> str | None:
    for key in ("target", "object", "element"):
        if key in params:
            return label_of(obs, params[key])
    return None


def validate_params(spec: ActionSpec, params: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(spec.params_schema)
    return [f"{'/'.join(map(str, e.path)) or '$'}: {e.message}" for e in validator.iter_errors(params)][:5]


def _postconditions(spec: ActionSpec) -> list[Any]:
    return [p.model_dump(by_alias=True, mode="json") for p in spec.postconditions]


async def propose_action(session: Session, args: dict[str, Any]) -> dict[str, Any]:
    conn = session.conn
    if conn is None:
        return {"ok": False, "error": "no application is connected"}
    action_id = str(args.get("action_id", ""))
    params = args.get("params") or {}
    mode = args.get("mode", "guide")
    rationale = str(args.get("rationale", ""))[:300]
    if not isinstance(params, dict):
        return {"ok": False, "error": "params must be an object"}
    if mode not in ("guide", "do"):
        return {"ok": False, "error": "mode must be 'guide' or 'do'"}
    try:
        specs = {s.id: s for s in await conn.get_actions()}
    except WyspError as exc:
        return {"ok": False, "error": exc.message}
    spec = specs.get(action_id)
    if spec is None:
        return {"ok": False, "error": f"unknown action '{action_id}'", "available": sorted(specs)}
    problems = validate_params(spec, params)
    if problems:
        return {"ok": False, "error": "invalid parameters", "problems": problems, "params_schema": spec.params_schema}
    if mode == "do" and not conn.manifest.has("execute"):
        mode = "guide"
    obs = await session.observe()
    if mode == "guide":
        return await _start_guide(session, conn, spec, params, obs)
    return await _do_action(session, conn, spec, params, rationale, obs)


# ---------------------------------------------------------------------------------- guide
async def _start_guide(
    session: Session, conn: Any, spec: ActionSpec, params: dict[str, Any], obs: Observation
) -> dict[str, Any]:
    from ..session.session import Watch

    post = _postconditions(spec)
    if post:
        already = await verify(conn, post, params)
        if already.ok:
            return {"ok": True, "status": "already_satisfied", "message": "The application is already in that state."}
    title = localized(spec.title, session.lang)
    steps_src = spec.guide.ui_path if spec.guide else []
    steps = []
    for i, gs in enumerate(steps_src, start=1):
        ref = render_ref(gs.target, params)
        node = node_id(ref) if ref and session.board.node(node_id(ref)) else None
        steps.append(
            {
                "id": f"s{i}",
                "index": i - 1,
                "text": render_template(localized(gs.text, session.lang), params, obs),
                "status": "active" if i == 1 else "pending",
                "target": node,
            }
        )
    if not steps:
        steps = [
            {
                "id": "s1",
                "index": 0,
                "text": f"{title} ({target_label(spec, params, obs) or ''})".strip(),
                "status": "active",
                "target": None,
            }
        ]
    await session.apply_board([{"op": "set_steps", "steps": steps}], validate=False)
    first_ref = render_ref(steps_src[0].target, params) if steps_src else None
    if first_ref:
        await session.highlight_ref(first_ref)
    session.watch = Watch(conn.adapter_id, spec.id, title, params, post, [s["id"] for s in steps])
    session.audit.append("guide_started", action_id=spec.id, params=params)
    session.tm.emit(
        "guide.start",
        full={"params": params, "steps": [s["text"] for s in steps]},
        action_id=spec.id,
        n_steps=len(steps),
        postconditions=len(post),
    )
    return {
        "ok": True,
        "status": "waiting_for_user",
        "mode": "guide",
        "steps": [s["text"] for s in steps],
        "note": "The user performs these steps in the application. Wysp will verify the result and announce it.",
    }


async def check_watch(session: Session) -> None:
    watch = session.watch
    conn = session.conn
    if watch is None or conn is None or conn.adapter_id != watch.adapter_id:
        return
    result = await verify(conn, watch.postconditions, watch.params)
    session.tm.emit(
        "guide.check",
        action_id=watch.action_id,
        ok=result.ok,
        full={"failure": None if result.ok else result.failure_summary()},
    )
    if not result.ok:
        return
    session.watch = None
    session.tm.emit("guide.verified", action_id=watch.action_id)
    await session.apply_board(
        [{"op": "update_step", "id": sid, "status": "done"} for sid in watch.step_ids], validate=False
    )
    evidence = result.evidence("verified")
    session.audit.append("guide_verified", action_id=watch.action_id, evidence_id=evidence.id)
    await session.broadcast(
        {
            "type": "evidence.added",
            "evidence": evidence.model_dump(mode="json"),
            "title": watch.title,
            "scope": "user_action",
        }
    )
    await session.narrate(f"Verified in the application: {watch.title}. Well done, you did that yourself.")


# ------------------------------------------------------------------------------------- do
async def _do_action(
    session: Session, conn: Any, spec: ActionSpec, params: dict[str, Any], rationale: str, obs: Observation
) -> dict[str, Any]:
    title = localized(spec.title, session.lang)
    preview = None
    if spec.risk == "irreversible":
        try:
            dry = await conn.execute(ActionCall(action_id=spec.id, params=params, request_id="preview", dry_run=True))
            preview = dry.preview
        except WyspError:
            preview = None
    proposal = Proposal(
        action_id=spec.id,
        title=title,
        params=params,
        rationale=rationale,
        risk=spec.risk,
        reversible=spec.reversible,
        target_label=target_label(spec, params, obs),
        preview=preview,
    )
    approval = await session.gate.request(proposal, conn.manifest.integration_level)
    if not approval.approved:
        return {
            "ok": False,
            "status": "denied",
            "reason": f"not approved ({approval.by})",
            "message": "The user did not approve this action.",
        }

    await session.set_status("acting")
    try:
        with session.tm.span("action.execute", full={"params": params}, action_id=spec.id, risk=spec.risk) as ex:
            result = await conn.execute(ActionCall(action_id=spec.id, params=params, request_id=proposal.id))
            ex["changed"] = len(result.changed)
            ex["undo_token"] = bool(result.undo_token)
    except WyspError as exc:
        session.audit.append("execution", request_id=proposal.id, action_id=spec.id, ok=False, error=exc.message)
        return {"ok": False, "status": "failed", "error": exc.message, "code": exc.code}
    session.audit.append(
        "execution",
        request_id=proposal.id,
        action_id=spec.id,
        ok=result.status == "ok",
        changed=result.changed,
        undo=bool(result.undo_token),
    )
    if result.status != "ok":
        return {"ok": False, "status": "failed", "error": result.message or "the application reported a failure"}
    if result.undo_token:
        session.undo.push(conn.adapter_id, UndoRecord(proposal.id, spec.id, title, result.undo_token))

    post = _postconditions(spec)
    if not post:
        await session.refresh_board()
        return {
            "ok": True,
            "status": "executed_unverified",
            "changed": result.changed,
            "message": "Done, but this action declares no way to verify it.",
        }
    t_verify = time.monotonic()
    check = await verify(conn, post, params)
    session.tm.emit(
        "action.verify",
        full={"failure": None if check.ok else check.failure_summary()},
        action_id=spec.id,
        ok=check.ok,
        duration_ms=round((time.monotonic() - t_verify) * 1000, 1),
    )
    if check.ok:
        evidence = check.evidence("verified")
        session.audit.append("verification", request_id=proposal.id, ok=True, evidence_id=evidence.id)
        await session.broadcast(
            {
                "type": "evidence.added",
                "evidence": evidence.model_dump(mode="json"),
                "title": title,
                "scope": "wysp_action",
            }
        )
        await session.refresh_board()
        return {
            "ok": True,
            "status": "verified",
            "changed": result.changed,
            "undo_available": bool(result.undo_token),
            "message": f"{title}: done and verified in the application.",
        }
    # Verification failed: undo when possible and report with the evidence.
    summary = check.failure_summary()
    session.audit.append("verification", request_id=proposal.id, ok=False, summary=summary)
    undone = False
    if result.undo_token:
        try:
            await conn.undo(result.undo_token)
            session.undo.remove(conn.adapter_id, result.undo_token)
            undone = True
            session.audit.append("undo", request_id=proposal.id, action_id=spec.id, by="auto")
        except WyspError as exc:
            log.warning("automatic undo failed: %s", exc.message)
    await session.refresh_board()
    return {
        "ok": False,
        "status": "failed_and_undone" if undone else "failed",
        "error": f"The action ran but the result could not be verified: {summary}",
        "undone": undone,
    }
