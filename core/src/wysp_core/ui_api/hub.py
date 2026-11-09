"""Hub of connected Panels: broadcast Core to Panel messages."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

log = logging.getLogger("wysp.ui")


class UiSocket(Protocol):
    async def send_text(self, data: str) -> None: ...


class UiHub:
    def __init__(self) -> None:
        self._clients: set[UiSocket] = set()
        self._lock = asyncio.Lock()
        self.sent: list[dict[str, Any]] = []  # recent messages, handy for tests and debugging
        self._keep = 500

    def add(self, ws: UiSocket) -> None:
        self._clients.add(ws)

    def remove(self, ws: UiSocket) -> None:
        self._clients.discard(ws)

    @property
    def count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        del self.sent[: max(0, len(self.sent) - self._keep)]
        if not self._clients:
            return
        data = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            for ws in list(self._clients):
                try:
                    await ws.send_text(data)
                except Exception:  # noqa: BLE001 - a dead client must not break the others
                    self._clients.discard(ws)

    async def send_to(self, ws: UiSocket, message: dict[str, Any]) -> None:
        await ws.send_text(json.dumps(message, ensure_ascii=False))
