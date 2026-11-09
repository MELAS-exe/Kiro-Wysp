"""PanelClient: connects Blender to the Core's UI protocol (``/ws/ui``), like the browser Panel does.

A background thread owns the socket and only queues inbound messages; the Blender main thread drains
them (``drain``) into a ``UiState`` from the add-on's timer. ``send`` is safe from any thread. The
Core listens on 127.0.0.1 only; a native client sends no Origin header, as the gateway expects.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any

import websocket  # websocket-client, bundled with the extension

log = logging.getLogger("wysp.blender.ui")


class PanelClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self.status = "stopped"
        self.last_error: str | None = None
        self._ws: websocket.WebSocket | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="wysp-panel-net", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._thread:
            self._thread.join(timeout=3)
        self.status = "stopped"

    @property
    def connected(self) -> bool:
        return self.status == "connected"

    def send(self, message: dict[str, Any]) -> bool:
        ws = self._ws
        if ws is None or not self.connected:
            return False
        try:
            with self._lock:
                ws.send(json.dumps(message, ensure_ascii=False))
            return True
        except Exception as exc:  # noqa: BLE001
            log.debug("ui send failed: %s", exc)
            return False

    def drain(self, limit: int = 200) -> list[dict[str, Any]]:
        out = []
        while len(out) < limit:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                break
        return out

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            self.status = "connecting"
            try:
                ws = websocket.create_connection(self.url, timeout=5, suppress_origin=True)
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"cannot reach the Core: {exc}"
                self.status = "disconnected"
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 5.0)
                continue
            ws.settimeout(1.0)
            self._ws = ws
            self.status = "connected"
            self.last_error = None
            self.inbox.put({"type": "_connected"})
            backoff = 0.5
            try:
                while not self._stop.is_set():
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not raw:
                        break
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(msg, dict):
                        self.inbox.put(msg)
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"connection lost: {exc}"
            finally:
                self._ws = None
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass
                self.status = "disconnected"
                self.inbox.put({"type": "_disconnected"})
            self._stop.wait(backoff)
