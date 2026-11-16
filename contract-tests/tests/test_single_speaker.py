"""Only one Panel speaks: a second window shows captions but never reads the same sentence twice."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

import websockets


class _Raw:
    """A second Panel: collects what the Core sends it."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.messages: list[dict] = []
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        with contextlib.suppress(Exception):
            async for raw in self.ws:
                self.messages.append(json.loads(raw))

    async def send(self, **msg) -> None:
        await self.ws.send(json.dumps(msg))

    def segments(self) -> list[dict]:
        return [m for m in self.messages if m.get("type") == "narration.segment"]


async def _until(pred, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


async def test_one_panel_speaks_and_only_it_drives_the_timeline(make_stack):
    s = await make_stack([])
    second = _Raw(await websockets.connect(f"ws://127.0.0.1:{s.port}/ws/ui"))
    try:
        await _until(lambda: s.session.hub.count == 2)

        await s.session.narrate("First sentence.")
        await _until(lambda: second.segments() and s.ui.of_type("narration.segment"))
        first_panel = s.ui.of_type("narration.segment")[0]
        assert first_panel["speaker"] is True  # connected first
        assert second.segments()[0]["speaker"] is False
        seg_id = first_panel["segment"]["id"]

        # A silent mirror's report is ignored; the speaking Panel's counts.
        await second.send(type="narration.progress", segment_id=seg_id, played=True)
        await asyncio.sleep(0.2)
        assert seg_id not in s.session.narration.played
        await s.ui.send(type="narration.progress", segment_id=seg_id, played=True)
        await _until(lambda: seg_id in s.session.narration.played)

        # The user acts in the second Panel: it speaks from now on.
        await second.send(type="settings.update", lang="en")
        await asyncio.sleep(0.2)
        await s.session.narrate("Second sentence.")
        await _until(lambda: len(second.segments()) >= 2 and len(s.ui.of_type("narration.segment")) >= 2)
        assert second.segments()[-1]["speaker"] is True
        assert s.ui.of_type("narration.segment")[-1]["speaker"] is False

        # The speaker leaves: the remaining Panel takes over.
        await second.ws.close()
        await _until(lambda: s.session.hub.count == 1)
        await s.session.narrate("Third sentence.")
        await _until(lambda: len(s.ui.of_type("narration.segment")) >= 3)
        assert s.ui.of_type("narration.segment")[-1]["speaker"] is True
    finally:
        with contextlib.suppress(Exception):
            await second.ws.close()
