"""Dispatchers: where adapter handlers run.

Hosts like Blender only allow API access from their main thread. The network thread therefore
hands each request to a dispatcher; a `QueueDispatcher` is pumped by the host's main thread.
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable
from typing import Any, Protocol

Done = Callable[[Any, BaseException | None], None]


class Dispatcher(Protocol):
    def submit(self, fn: Callable[[], Any], done: Done) -> None: ...


class ImmediateDispatcher:
    """Runs the handler on the calling (network) thread. For hosts without thread rules."""

    def submit(self, fn: Callable[[], Any], done: Done) -> None:
        try:
            result = fn()
        except BaseException as exc:  # noqa: BLE001 - forwarded to `done`
            done(None, exc)
        else:
            done(result, None)


class QueueDispatcher:
    """Queues handlers; `pump()` runs them on whichever thread calls it (the host main thread)."""

    def __init__(self) -> None:
        self._q: queue.Queue[tuple[Callable[[], Any], Done]] = queue.Queue()

    def submit(self, fn: Callable[[], Any], done: Done) -> None:
        self._q.put((fn, done))

    def pending(self) -> int:
        return self._q.qsize()

    def pump(self, budget_s: float = 0.02) -> int:
        """Run queued jobs until the budget is spent. Returns how many ran. Always runs at least one."""
        deadline = time.monotonic() + budget_s
        ran = 0
        while True:
            try:
                fn, done = self._q.get_nowait()
            except queue.Empty:
                return ran
            try:
                result = fn()
            except BaseException as exc:  # noqa: BLE001
                done(None, exc)
            else:
                done(result, None)
            ran += 1
            if time.monotonic() >= deadline:
                return ran
