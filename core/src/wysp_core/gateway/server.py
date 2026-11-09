"""The /ws/adapter endpoint: handshake, heartbeat watchdog and message routing."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .. import __version__
from ..contract import (
    CONTRACT_VERSION,
    ErrorCode,
    HelloParams,
    HelloResult,
    Navigation,
    SelectionChanged,
    StateChanged,
    UserAction,
)
from ..contract.rpc import error_response, ok_response, split_version
from ..store import redact_text
from .connection import AdapterConnection
from .registry import AdapterRegistry

log = logging.getLogger("wysp.gateway")

HEARTBEAT_INTERVAL_S = 20.0
WATCHDOG_S = 45.0
HELLO_TIMEOUT_S = 10.0

EVENT_MODELS = {
    "event.state_changed": ("state_changed", StateChanged),
    "event.selection_changed": ("selection_changed", SelectionChanged),
    "event.user_action": ("user_action", UserAction),
    "event.navigation": ("navigation", Navigation),
}


class WebSocketTransport:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._lock = asyncio.Lock()

    async def send_json(self, message: dict[str, Any]) -> None:
        async with self._lock:
            await self.ws.send_text(json.dumps(message, ensure_ascii=False))

    async def close(self, code: int = 1000) -> None:
        try:
            await self.ws.close(code=code)
        except RuntimeError:
            pass


def origin_allowed(origin: str | None, allowed: set[str]) -> bool:
    """Native clients send no Origin header. Browsers send one that must be allowlisted.

    An allowlist entry ending in `*` is a prefix pattern (configured by the user, for example for
    a browser extension identified by its own origin scheme).
    """
    if origin is None:
        return True
    if origin in allowed:
        return True
    return any(entry.endswith("*") and origin.startswith(entry[:-1]) for entry in allowed)


async def serve_adapter(ws: WebSocket, registry: AdapterRegistry, token: str, allowed_origins: set[str]) -> None:
    if not origin_allowed(ws.headers.get("origin"), allowed_origins):
        await ws.close(code=4403)
        return
    await ws.accept()
    transport = WebSocketTransport(ws)
    conn: AdapterConnection | None = None
    try:
        conn = await _handshake(ws, transport, registry, token)
        if conn is None:
            return
        await _read_loop(ws, conn, registry)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:  # noqa: BLE001
        log.exception("adapter connection failed")
    finally:
        if conn is not None:
            conn.fail_all("adapter disconnected")
            registry.remove(conn)


async def _handshake(
    ws: WebSocket, transport: WebSocketTransport, registry: AdapterRegistry, token: str
) -> AdapterConnection | None:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S)
        msg = json.loads(raw)
    except (TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
        await transport.close(4400)
        return None
    request_id = msg.get("id")
    if msg.get("method") != "wysp.hello":
        await transport.send_json(
            error_response(request_id, ErrorCode.INVALID_REQUEST, "first message must be wysp.hello")
        )
        await transport.close(4400)
        return None
    params = msg.get("params") or {}
    if not hmac.compare_digest(str(params.get("token", "")), token):
        await transport.send_json(error_response(request_id, ErrorCode.UNAUTHORIZED, "bad pairing token"))
        await transport.close(4401)
        return None
    try:
        hello = HelloParams.model_validate(params)
    except ValidationError as exc:
        await transport.send_json(
            error_response(
                request_id, ErrorCode.INVALID_PARAMS, "invalid manifest", {"errors": json.loads(exc.json())[:5]}
            )
        )
        await transport.close(4400)
        return None
    their_major = split_version(hello.manifest.contract_version)[0]
    our_major = split_version(CONTRACT_VERSION)[0]
    if their_major != our_major:
        await transport.send_json(
            error_response(
                request_id,
                ErrorCode.INCOMPATIBLE_VERSION,
                f"adapter speaks contract {hello.manifest.contract_version}, Core speaks {CONTRACT_VERSION}",
                {"adapter": hello.manifest.contract_version, "core": CONTRACT_VERSION},
            )
        )
        await transport.close(4409)
        return None
    session_id = uuid.uuid4().hex[:12]
    conn = AdapterConnection(transport, hello.manifest, session_id)
    previous = registry.add(conn)
    if previous is not None:
        previous.fail_all("replaced by a new connection")
        await previous.transport.close(4000)
    result = HelloResult(
        session_id=session_id,
        contract_version=CONTRACT_VERSION,
        core_version=__version__,
        heartbeat_interval_s=HEARTBEAT_INTERVAL_S,
    )
    await transport.send_json(ok_response(request_id, result.model_dump(mode="json")))
    log.info("adapter connected: %s (%s)", conn.adapter_id, hello.manifest.app.name)
    return conn


async def _read_loop(ws: WebSocket, conn: AdapterConnection, registry: AdapterRegistry) -> None:
    bus = registry.bus
    while True:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), WATCHDOG_S)
        except TimeoutError:
            log.warning("adapter %s silent for %.0fs, disconnecting", conn.adapter_id, WATCHDOG_S)
            await conn.transport.close(4408)
            return
        conn.last_seen = asyncio.get_running_loop().time()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        if method is None:
            conn.resolve(msg)
            continue
        params = msg.get("params") or {}
        if method == "wysp.heartbeat":
            sv = params.get("state_version")
            if isinstance(sv, int):
                conn.state_version = max(conn.state_version, sv)
        elif method == "wysp.bye":
            return
        elif method in EVENT_MODELS:
            name, model = EVENT_MODELS[method]
            try:
                data = model.model_validate(params)
            except ValidationError as exc:
                log.warning("invalid %s from %s: %s", method, conn.adapter_id, redact_text(str(exc))[:200])
                continue
            if isinstance(data, StateChanged):
                conn.state_version = max(conn.state_version, data.state_version)
            bus.publish("adapter.event", adapter_id=conn.adapter_id, name=name, data=data.model_dump(mode="json"))
        elif msg.get("id") is not None:
            await conn.transport.send_json(
                error_response(msg["id"], ErrorCode.METHOD_NOT_FOUND, f"adapters may not call {method}")
            )
