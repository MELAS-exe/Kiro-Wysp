"""The harness server of the Contract Test Kit [adapter-contract 9].

A tiny JSON-RPC 2.0 WebSocket server that plays the Core's part towards one adapter: it checks the pairing token
and the Origin, answers `wysp.hello`, then lets the kit send requests (`request`, blocking) while it records every
message and collects the adapter's notifications. It is independent of `wysp_core.gateway` (it depends on the
contract models only), so a bug in the Core's gateway cannot hide a bug in an adapter, or the other way round.

    harness = Harness(token)          # listens on 127.0.0.1, free port
    harness.start()
    ...launch the adapter with harness.url and the token...
    harness.wait_connected(timeout)
    harness.request("adapter.observe", {"scope": {"level": "full"}})
    harness.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import itertools
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import websockets
from pydantic import ValidationError
from wysp_core.contract import CONTRACT_VERSION, ErrorCode, HelloParams, HelloResult, Manifest, WyspError
from wysp_core.contract.rpc import BUDGETS_S, error_response, ok_response, split_version

SLACK_S = 1.0  # the Core adds the same slack to the contract budgets (network hop, host dispatch pump)
HELLO_TIMEOUT_S = 10.0
SECRET_KEYS = {"token", "password", "api_key", "secret", "authorization"}


@dataclass
class Event:
    t: float  # time.monotonic() on arrival
    method: str
    params: dict[str, Any]


@dataclass
class Timing:
    method: str
    seconds: float
    ok: bool


def redact(value: Any) -> Any:
    """Copy of a message with the values of secret-looking keys replaced (recordings must never hold a token)."""
    if isinstance(value, dict):
        return {k: "***" if k.lower() in SECRET_KEYS else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@dataclass
class Harness:
    token: str
    host: str = "127.0.0.1"
    allowed_origins: set[str] = field(default_factory=set)
    port: int = 0
    manifest: Manifest | None = None
    events: list[Event] = field(default_factory=list)
    timings: list[Timing] = field(default_factory=list)
    recording: list[dict[str, Any]] = field(default_factory=list)
    connections: int = 0
    handshake_error: str | None = None

    def __post_init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="wysp-harness", daemon=True)
        self._server: Any = None
        self._ws: Any = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = threading.Event()
        self._t0 = time.monotonic()

    # ------------------------------------------------------------------------------ lifecycle
    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws/adapter"

    def start(self) -> None:
        self._thread.start()

        async def serve() -> None:
            self._server = await websockets.serve(self._handler, self.host, self.port, ping_interval=None)
            self.port = self._server.sockets[0].getsockname()[1]

        asyncio.run_coroutine_threadsafe(serve(), self._loop).result(10)

    def stop(self) -> None:
        async def close() -> None:
            if self._ws is not None:
                with contextlib.suppress(Exception):
                    await self._ws.close()
            if self._server is not None:
                self._server.close()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._server.wait_closed(), 3)
            rest = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in rest:  # a handler still waiting on a half-closed socket must not outlive the loop
                task.cancel()
            await asyncio.gather(*rest, return_exceptions=True)

        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(close(), self._loop).result(8)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)
        if not self._thread.is_alive():
            self._loop.close()

    def wait_connected(self, timeout: float, alive: Callable[[], str | None] = lambda: None) -> str | None:
        """Wait for the adapter's hello. Return None when connected, else why not (timeout, launcher died...)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._connected.wait(0.2):
                return None
            if self.handshake_error:
                return self.handshake_error
            if (reason := alive()) is not None:
                return reason
        return f"the adapter did not connect within {timeout:.0f}s"

    # ---------------------------------------------------------------------------------- server
    def _record(self, direction: str, message: Any) -> None:
        self.recording.append(
            {"t": round(time.monotonic() - self._t0, 3), "dir": direction, "message": redact(message)}
        )

    def _origin_ok(self, origin: str | None) -> bool:
        return origin is None or origin in self.allowed_origins

    async def _handler(self, ws: Any) -> None:
        origin = ws.request.headers.get("Origin")
        if ws.request.path != "/ws/adapter" or not self._origin_ok(origin):
            self.handshake_error = f"connection refused (path {ws.request.path}, origin {origin})"
            await ws.close(4403)
            return
        try:
            raw = await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S)
            msg = json.loads(raw)
        except (TimeoutError, json.JSONDecodeError, websockets.ConnectionClosed):
            return
        self._record("from_adapter", msg)
        rid = msg.get("id")

        async def refuse(code: int, text: str, close: int) -> None:
            self.handshake_error = text
            reply = error_response(rid, code, text)
            self._record("to_adapter", reply)
            await ws.send(json.dumps(reply))
            await ws.close(close)

        if msg.get("method") != "wysp.hello":
            return await refuse(ErrorCode.INVALID_REQUEST, "first message must be wysp.hello", 4400)
        params = msg.get("params") or {}
        if not hmac.compare_digest(str(params.get("token", "")), self.token):
            return await refuse(ErrorCode.UNAUTHORIZED, "bad pairing token", 4401)
        try:
            hello = HelloParams.model_validate(params)
        except ValidationError as exc:
            return await refuse(ErrorCode.INVALID_PARAMS, f"invalid manifest: {exc.errors()[0]['msg']}", 4400)
        if split_version(hello.manifest.contract_version)[0] != split_version(CONTRACT_VERSION)[0]:
            return await refuse(
                ErrorCode.INCOMPATIBLE_VERSION,
                f"adapter speaks contract {hello.manifest.contract_version}, the kit speaks {CONTRACT_VERSION}",
                4409,
            )
        self.manifest = hello.manifest
        self.connections += 1
        self._ws = ws
        result = HelloResult(session_id="kit", contract_version=CONTRACT_VERSION, core_version="kit")
        reply = ok_response(rid, result.model_dump(mode="json"))
        self._record("to_adapter", reply)
        await ws.send(json.dumps(reply))
        self._connected.set()
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._record("from_adapter", msg)
                method = msg.get("method")
                if method is None:
                    fut = self._pending.pop(msg.get("id"), None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                elif method == "wysp.bye":
                    return
                elif method != "wysp.heartbeat" and msg.get("id") is None:
                    self.events.append(Event(time.monotonic(), method, msg.get("params") or {}))
        except websockets.ConnectionClosed:
            pass
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(WyspError(ErrorCode.TIMEOUT, "adapter disconnected"))
            self._pending.clear()
            if self._ws is ws:
                self._ws = None
                self._connected.clear()

    # ---------------------------------------------------------------------------------- calls
    async def _call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        if self._ws is None:
            raise WyspError(ErrorCode.TIMEOUT, "adapter is not connected")
        rid = next(self._ids)
        fut: asyncio.Future = self._loop.create_future()
        self._pending[rid] = fut
        message = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        self._record("to_adapter", message)
        started = time.monotonic()
        ok = False
        try:
            await self._ws.send(json.dumps(message))
            reply = await asyncio.wait_for(fut, timeout)
            if reply.get("error") is not None:
                err = reply["error"]
                raise WyspError(err.get("code", ErrorCode.INTERNAL_ERROR), err.get("message", ""), err.get("data"))
            ok = True
            return reply.get("result")
        except TimeoutError as exc:
            raise WyspError(ErrorCode.TIMEOUT, f"{method} exceeded {timeout:.1f}s") from exc
        finally:
            self._pending.pop(rid, None)
            self.timings.append(Timing(method, time.monotonic() - started, ok or fut.done()))

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        """Blocking JSON-RPC request to the adapter. Raises `WyspError` for an error response or a timeout."""
        budget = (timeout if timeout is not None else BUDGETS_S.get(method, 5.0)) + SLACK_S
        future = asyncio.run_coroutine_threadsafe(self._call(method, params or {}, budget), self._loop)
        return future.result(budget + 5)

    def over_budget(self) -> list[str]:
        """Requests that took longer than their contract budget plus the Core's slack."""
        return [
            f"{t.method} took {t.seconds:.2f}s (budget {BUDGETS_S[t.method]:.1f}s + {SLACK_S:.1f}s)"
            for t in self.timings
            if t.method in BUDGETS_S and t.seconds > BUDGETS_S[t.method] + SLACK_S
        ]
