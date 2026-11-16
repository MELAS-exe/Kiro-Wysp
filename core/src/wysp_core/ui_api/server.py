"""The /ws/ui endpoint: Panel messages in, Core messages out."""

from __future__ import annotations

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..board import node_id
from ..contract.ui import (
    AdapterActivate,
    BoardAskWhy,
    BoardSelect,
    ExploreStart,
    ExploreStop,
    NarrationCue,
    NarrationProgress,
    PermissionRespond,
    SettingsUpdate,
    SnapshotRequest,
    UndoLast,
    UserContinue,
    UserInterrupt,
    UserMessage,
    inbound_adapter,
)
from ..gateway.server import origin_allowed
from ..session.session import Session
from .hub import UiHub

log = logging.getLogger("wysp.ui")

# High-frequency bookkeeping messages, already covered by narration telemetry.
QUIET_UI_MESSAGES = {"narration.progress", "narration.cue", "board.snapshot_request"}
# Messages that do not mean the user is using this Panel (bookkeeping, or a Panel catching up).
PASSIVE_UI_MESSAGES = QUIET_UI_MESSAGES


async def serve_ui(ws: WebSocket, session: Session, hub: UiHub, allowed_origins: set[str]) -> None:
    if not origin_allowed(ws.headers.get("origin"), allowed_origins):
        await ws.close(code=4403)
        return
    await ws.accept()
    hub.add(ws)
    # Browsers send an Origin header; native Panels (the one inside the application) do not.
    client = "browser" if ws.headers.get("origin") else "native"
    try:
        for message in session.snapshot_messages():
            await hub.send_to(ws, message)
        while True:
            raw = await ws.receive_text()
            try:
                msg = inbound_adapter.validate_python(json.loads(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                await hub.send_to(ws, {"type": "error", "code": "bad_message", "message": str(exc)[:200]})
                continue
            if msg.type not in QUIET_UI_MESSAGES:
                # Who clicked what, from which window: makes "something pressed undo" traceable.
                session.tm.emit("ui.message", full={"message": msg.model_dump()}, type=msg.type, client=client)
            if msg.type not in PASSIVE_UI_MESSAGES:
                hub.touch(ws)  # the user is here: this Panel speaks from now on
            await handle_ui_message(session, hub, ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws)


async def handle_ui_message(session: Session, hub: UiHub, ws, msg) -> None:
    if isinstance(msg, UserMessage):
        await session.broadcast({"type": "chat.user", "text": msg.text, "source": msg.source})
        await session.user_message(msg.text, msg.source)
    elif isinstance(msg, UserInterrupt):
        await session.interrupt()
    elif isinstance(msg, UserContinue):
        await session.resume()
    elif isinstance(msg, PermissionRespond):
        ok, reason = session.gate.respond(msg.request_id, msg.decision, msg.via)
        if not ok:
            await session.broadcast({"type": "error", "code": "permission_refused", "message": reason})
    elif isinstance(msg, BoardSelect):
        node = session.board.node(msg.node_id)
        if node is not None:
            await session.apply_board([{"op": "set_focus", "ids": [node.id]}], validate=False)
            if node.ref and node.provenance == "observed":
                await session.highlight_ref(node.ref)
    elif isinstance(msg, BoardAskWhy):
        node = session.board.node(msg.node_id)
        if node is not None:
            kind = "real element of your project" if node.provenance == "observed" else f"{node.provenance} element"
            question = (
                f"Why is “{node.label}” on the board, and what does it do? (It is a {kind}; ref: {node.ref or 'none'}.)"
            )
            await session.broadcast({"type": "chat.user", "text": f"Why “{node.label}”?", "source": "typed"})
            await session.user_message(question, "typed")
    elif isinstance(msg, NarrationProgress):
        if hub.is_speaker(ws):  # only the Panel that speaks drives the narration timeline
            await session.on_narration_progress(msg.segment_id, msg.played)
    elif isinstance(msg, NarrationCue):
        if hub.is_speaker(ws):
            await session.on_narration_cue(msg.segment_id, msg.index)
    elif isinstance(msg, AdapterActivate):
        await session.activate(msg.adapter_id)
    elif isinstance(msg, SnapshotRequest):
        for message in session.snapshot_messages():
            await hub.send_to(ws, message)
    elif isinstance(msg, UndoLast):
        text = await session.undo_last()
        session.narration.new_turn()
        await session.narrate(text)
    elif isinstance(msg, SettingsUpdate):
        if msg.lang:
            session.lang = msg.lang
            await session.send_state()
        if msg.logging:
            await session.set_logging(msg.logging)
    elif isinstance(msg, ExploreStart):
        session.tm.emit("explore.accepted", phase=session.explorer.phase)
        await session.explorer.start()
    elif isinstance(msg, ExploreStop):
        await session.explorer.stop()


__all__ = ["handle_ui_message", "node_id", "serve_ui"]
