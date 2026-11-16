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
        # Exactly one Panel speaks, so a second window (the IDE's tool window and a browser tab, say) never reads
        # the same sentence twice. It is the Panel the user touched last, or the first one connected.
        self._speaker: UiSocket | None = None
        self._lock = asyncio.Lock()
        self.sent: list[dict[str, Any]] = []  # recent messages, handy for tests and debugging
        self._keep = 500

    def add(self, ws: UiSocket) -> None:
        self._clients.add(ws)
        if self._speaker is None:
            self._speaker = ws

    def remove(self, ws: UiSocket) -> None:
        self._clients.discard(ws)
        if self._speaker is ws:
            self._speaker = next(iter(self._clients), None)

    def touch(self, ws: UiSocket) -> None:
        """The user did something in this Panel: it speaks from now on."""
        if ws in self._clients:
            self._speaker = ws

    def is_speaker(self, ws: UiSocket) -> bool:
        return ws is self._speaker

    @property
    def count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        del self.sent[: max(0, len(self.sent) - self._keep)]
        if not self._clients:
            return
        shared = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            for ws in list(self._clients):
                # Narration tells each Panel whether it is the one that speaks and reports progress.
                data = (
                    json.dumps({**message, "speaker": ws is self._speaker}, ensure_ascii=False)
                    if message.get("type") == "narration.segment"
                    else shared
                )
                try:
                    await ws.send_text(data)
                except Exception:  # noqa: BLE001 - a dead client must not break the others
                    self._clients.discard(ws)

    async def send_to(self, ws: UiSocket, message: dict[str, Any]) -> None:
        await ws.send_text(json.dumps(message, ensure_ascii=False))
