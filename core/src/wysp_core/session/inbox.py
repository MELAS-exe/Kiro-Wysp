"""Events for an external AI agent: what the user said or did in the Panel while the agent drives the tutor."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

MAX_EVENTS = 50
MAX_WAIT_S = 55.0  # below the usual 60 s client timeout for a tool call


class UserInbox:
    """FIFO of user events (`message`, `interrupt`, `continue`). The oldest are dropped when full."""

    def __init__(self) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._ready = asyncio.Event()

    def put(self, kind: str, **payload: Any) -> None:
        self._events.append({"kind": kind, "at": round(time.time(), 3), **payload})
        self._ready.set()

    def pending(self) -> int:
        return len(self._events)

    def drain(self) -> list[dict[str, Any]]:
        events = list(self._events)
        self._events.clear()
        self._ready.clear()
        return events

    async def wait(self, timeout_s: float) -> list[dict[str, Any]]:
        """Return the queued events, waiting up to `timeout_s` for the first one (empty list on timeout)."""
        timeout_s = max(0.0, min(float(timeout_s), MAX_WAIT_S))
        if not self._events:
            try:
                await asyncio.wait_for(self._ready.wait(), timeout_s)
            except TimeoutError:
                return []
        return self.drain()
