"""A small asyncio event bus: publish dict events, handlers run as independent tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("wysp.bus")

Event = dict[str, Any]
Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[tuple[str | None, Handler]] = []
        self._tasks: set[asyncio.Task] = set()

    def subscribe(self, handler: Handler, topic: str | None = None) -> Callable[[], None]:
        entry = (topic, handler)
        self._handlers.append(entry)

        def unsubscribe() -> None:
            if entry in self._handlers:
                self._handlers.remove(entry)

        return unsubscribe

    def publish(self, topic: str, **payload: Any) -> None:
        event: Event = {"topic": topic, **payload}
        for wanted, handler in list(self._handlers):
            if wanted is None or wanted == topic:
                task = asyncio.get_running_loop().create_task(self._run(handler, event))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _run(self, handler: Handler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:  # noqa: BLE001
            log.exception("event handler failed for %s", event.get("topic"))

    async def drain(self) -> None:
        """Wait for in-flight handlers (used by tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
