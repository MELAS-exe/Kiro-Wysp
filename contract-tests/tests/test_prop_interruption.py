"""Interruption and resume properties CORE-P7 and CORE-P8 [core-orchestrator 9.1].

A real Session and TurnRunner run against a scripted LLM that narrates in several rounds. The interruption is
injected at an arbitrary point (while the model is thinking, or after the n-th segment was published), exactly as
a `user.interrupt` from the Panel would arrive in the middle of a turn.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from test_prop_provenance import make_session
from wysp_core.llm import LLMResult, ToolCall

FAST = settings(max_examples=40, deadline=None)

rounds_st = st.lists(st.integers(1, 4), min_size=1, max_size=4)  # segments narrated by each LLM round


class RoundsLLM:
    """Round r makes one `narrate` call carrying rounds[r] segments, then the turn ends."""

    name = "rounds"

    def __init__(self, rounds: list[int], on_round: Any = None) -> None:
        self.rounds, self.on_round, self.n = rounds, on_round, 0

    async def complete(self, messages, tools, cancel) -> LLMResult:
        r = self.n
        self.n += 1
        if self.on_round is not None:
            await self.on_round(r)
        if r >= len(self.rounds):
            return LLMResult(text="")
        segments = [{"text": f"Round {r} idea {i}."} for i in range(self.rounds[r])]
        return LLMResult(tool_calls=[ToolCall(f"t{r}", "narrate", {"segments": segments})])


def segments_and_cancels(session) -> list[tuple[str, Any]]:
    return [(m["type"], m) for m in session.hub.sent if m["type"] in ("narration.segment", "narration.cancel")]


async def settle(session) -> None:
    for _ in range(3):
        await asyncio.sleep(0)
    if session._turn_task is not None:
        await asyncio.wait({session._turn_task}, timeout=5)
    await session.bus.drain()


# ------------------------------------------------------------------------------------- CORE-P7
@FAST
@given(rounds_st, st.integers(0, 4), st.sampled_from(["llm", "segment"]), st.integers(1, 12))
def test_prop_core_p7_nothing_is_published_after_the_cancel(rounds, at_round, where, nth_segment) -> None:
    """CORE-P7: however a turn is interrupted, no narration segment of that turn is published after
    `narration.cancel`."""

    async def scenario() -> None:
        session, _ = make_session()
        fired = False

        async def interrupt_once() -> None:
            nonlocal fired
            if not fired:
                fired = True
                await session.interrupt()

        async def on_round(r: int) -> None:
            if where == "llm" and r == at_round:  # the user speaks while the model is thinking
                await interrupt_once()

        session.llm = RoundsLLM(rounds, on_round)
        if where == "segment":  # the user interrupts right after the n-th segment went out
            original = session.narrate
            sent = 0

            async def narrate(text, provenance="observed", cues=None):
                nonlocal sent
                count = await original(text, provenance, cues)
                sent += count
                if sent >= nth_segment:
                    await interrupt_once()
                return count

            session.narrate = narrate  # type: ignore[method-assign]

        await session.user_message("explain")
        await settle(session)
        events = segments_and_cancels(session)
        kinds = [k for k, _ in events]
        if "narration.cancel" in kinds:
            after = kinds[kinds.index("narration.cancel") + 1 :]
            assert "narration.segment" not in after, f"segment published after the cancel: {events}"

    asyncio.run(scenario())


# ------------------------------------------------------------------------------------- CORE-P8
@FAST
@given(st.lists(st.integers(1, 3), min_size=1, max_size=3), st.data())
def test_prop_core_p8_resume_replays_exactly_the_unplayed_segments(rounds, data) -> None:
    """CORE-P8: whatever was played before the interruption, `user.continue` publishes exactly the unplayed
    segments, in their original order, and only once."""

    async def scenario() -> None:
        session, _ = make_session()
        session.llm = RoundsLLM(rounds)
        await session.user_message("explain")
        await settle(session)
        published = [m["segment"] for m in session.hub.sent if m["type"] == "narration.segment"]
        assert len(published) == rounds[0]  # a round that only narrates ends the turn
        played = data.draw(st.lists(st.sampled_from(range(len(published))), unique=True, max_size=len(published)))
        for i in played:
            await session.on_narration_progress(published[i]["id"], True)
        await session.interrupt()
        cancel = [m for m in session.hub.sent if m["type"] == "narration.cancel"][-1]
        expected = [s for i, s in enumerate(published) if i not in set(played)]
        assert cancel["from_index"] == (expected[0]["index"] if expected else len(published))
        before = len(session.hub.sent)
        await session.resume()
        replayed = [m["segment"] for m in session.hub.sent[before:] if m["type"] == "narration.segment"]
        assert [s["id"] for s in replayed] == [s["id"] for s in expected]
        assert [s["index"] for s in replayed] == sorted(s["index"] for s in replayed)
        before = len(session.hub.sent)
        await session.resume()
        assert [m for m in session.hub.sent[before:] if m["type"] == "narration.segment"] == []

    asyncio.run(scenario())
