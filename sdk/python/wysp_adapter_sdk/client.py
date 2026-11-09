"""WebSocket client: connects an adapter to Wysp Core and routes JSON-RPC messages.

Runs a background thread. Requests from the Core are handed to a dispatcher (so the host can run
them on its main thread); responses are sent from whichever thread completes the job.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import websocket  # websocket-client

from .dispatch import Dispatcher, ImmediateDispatcher
from .errors import ErrorCode, WyspError

log = logging.getLogger("wysp.adapter")

Handler = Callable[[str, dict[str, Any]], Any]
HELLO_ID = "hello-1"


class AdapterClient:
    def __init__(
        self,
        manifest: dict[str, Any],
        url: str,
        token: str,
        handler: Handler,
        dispatcher: Dispatcher | None = None,
        heartbeat_s: float = 15.0,
        on_status: Callable[[str], None] | None = None,
        state_version: Callable[[], int] | None = None,
        on_request_done: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.manifest = manifest
        self.url = url
        self.token = token
        self.handler = handler
        self.dispatcher: Dispatcher = dispatcher or ImmediateDispatcher()
        self.heartbeat_s = heartbeat_s
        self._on_status = on_status
        self._state_version = state_version
        # Called after each request with {method, queue_ms, run_ms, ok, error_code}: host-side telemetry.
        self.on_request_done = on_request_done
        self._ws: websocket.WebSocket | None = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status = "stopped"
        self.session_id: str | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="wysp-adapter-net", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                self._send({"jsonrpc": "2.0", "method": "wysp.bye", "params": {"reason": "stop"}})
                ws.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
        if self._thread:
            self._thread.join(timeout=3)
        self._set_status("stopped")

    @property
    def connected(self) -> bool:
        return self.status == "connected"

    def _set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            log.info("adapter status: %s", status)
            if self._on_status:
                try:
                    self._on_status(status)
                except Exception:  # noqa: BLE001
                    log.exception("on_status callback failed")

    # ------------------------------------------------------------------------------ send
    def _send(self, message: dict[str, Any]) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            with self._send_lock:
                ws.send(json.dumps(message, ensure_ascii=False))
            return True
        except Exception as exc:  # noqa: BLE001
            log.debug("send failed: %s", exc)
            return False

    def notify(self, method: str, params: dict[str, Any] | None = None) -> bool:
        """Send a notification (no response expected). Safe to call from any thread."""
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        return self._send(msg)

    # ------------------------------------------------------------------------------ loop
    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            self._set_status("connecting")
            try:
                ws = websocket.create_connection(self.url, timeout=5, suppress_origin=True)
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"cannot reach Core: {exc}"
                self._set_status("disconnected")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 10.0)
                continue
            self._ws = ws
            ws.settimeout(1.0)
            try:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": HELLO_ID,
                        "method": "wysp.hello",
                        "params": {"manifest": self.manifest, "token": self.token},
                    }
                )
                backoff = 0.5
                self._recv_loop(ws)
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                log.debug("connection loop ended: %s", exc)
            finally:
                self._ws = None
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass
                self.session_id = None
                self._set_status("disconnected")
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 10.0)

    def _recv_loop(self, ws: websocket.WebSocket) -> None:
        last_hb = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if self.connected and now - last_hb >= self.heartbeat_s:
                sv = self._state_version() if self._state_version else None
                self.notify("wysp.heartbeat", {"state_version": sv} if sv is not None else {})
                last_hb = now
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if raw is None or raw == "":
                raise ConnectionError("closed by Core")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self._on_message(msg)

    # ---------------------------------------------------------------------------- inbound
    def _on_message(self, msg: dict[str, Any]) -> None:
        if "method" in msg:
            self._on_request(msg)
            return
        if msg.get("id") == HELLO_ID:
            if "error" in msg:
                err = msg["error"]
                self.last_error = f"hello refused ({err.get('code')}): {err.get('message')}"
                log.warning(self.last_error)
                self._set_status("refused")
                raise ConnectionError(self.last_error)
            result = msg.get("result") or {}
            self.session_id = result.get("session_id")
            self.heartbeat_s = min(self.heartbeat_s, float(result.get("heartbeat_interval_s", 20.0)))
            self.last_error = None
            self._set_status("connected")

    def _on_request(self, msg: dict[str, Any]) -> None:
        method = msg["method"]
        params = msg.get("params") or {}
        request_id = msg.get("id")
        timing: dict[str, float] = {"received": time.monotonic()}

        def run() -> Any:
            timing["started"] = time.monotonic()
            return self.handler(method, params)

        def done(result: Any, exc: BaseException | None) -> None:
            self._report(method, timing, exc)
            if request_id is None:
                return
            if exc is None:
                self._send({"jsonrpc": "2.0", "id": request_id, "result": result})
                return
            if isinstance(exc, WyspError):
                self._send({"jsonrpc": "2.0", "id": request_id, "error": exc.to_dict()})
                return
            log.exception("handler %s failed", method, exc_info=exc)
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": int(ErrorCode.EXECUTION_FAILED), "message": f"{type(exc).__name__}: {exc}"},
                }
            )

        self.dispatcher.submit(run, done)

    def _report(self, method: str, timing: dict[str, float], exc: BaseException | None) -> None:
        if self.on_request_done is None:
            return
        end = time.monotonic()
        started = timing.get("started", end)
        try:
            self.on_request_done(
                {
                    "method": method,
                    "queue_ms": round((started - timing["received"]) * 1000, 1),
                    "run_ms": round((end - started) * 1000, 1),
                    "ok": exc is None,
                    "error_code": int(exc.code) if isinstance(exc, WyspError) else (None if exc is None else -1),
                }
            )
        except Exception:  # noqa: BLE001 - telemetry must never break request handling
            pass
