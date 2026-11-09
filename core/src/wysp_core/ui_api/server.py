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


async def serve_ui(ws: WebSocket, session: Session, hub: UiHub, allowed_origins: set[str]) -> None:
    if not origin_allowed(ws.headers.get("origin"), allowed_origins):
        await ws.close(code=4403)
        return
    await ws.accept()
    hub.add(ws)
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
        await session.on_narration_progress(msg.segment_id, msg.played)
    elif isinstance(msg, NarrationCue):
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


__all__ = ["handle_ui_message", "node_id", "serve_ui"]
