"""Persistent highlights [core-orchestrator 19, adapter-contract 8.3-8.6]: they stay until the tutor or the user is done."""

from __future__ import annotations

import asyncio
import time

from wysp_core.orchestrator.context import build_system_prompt
from wysp_core.orchestrator.tools import ToolBox
from wysp_core.session import session as session_mod
from wysp_mock.kanban import card_ref

C1, C2 = card_ref("c1"), card_ref("c2")


async def _until(pred, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


async def test_pointing_at_something_stays_until_cleared(make_stack):
    s = await make_stack([])
    box = ToolBox(s.session)

    assert (await box.call("highlight", {"ref": C1}))["ok"]
    assert s.mock.highlight_log[-1] == (C1, 0)  # persistent: no timer on the adapter's side
    assert s.session.active_highlight.ref == C1
    assert "Highlighted in the application now" in await build_system_prompt(s.session)

    # Pointing at something else replaces it: one highlight at a time.
    assert (await box.call("highlight", {"ref": C2}))["ok"]
    assert s.session.active_highlight.ref == C2 and s.mock.highlight_active == C2

    # The tutor takes it down.
    out = await box.call("clear_highlight", {})
    assert out == {"ok": True, "cleared": True}
    assert s.session.active_highlight is None and s.mock.highlight_active is None
    assert "Highlighted in the application now" not in await build_system_prompt(s.session)

    # Nothing left to clear: harmless, and the adapter is not bothered.
    clears = s.mock.highlight_clears
    assert (await box.call("clear_highlight", {})) == {"ok": True, "cleared": False}
    assert s.mock.highlight_clears == clears


async def test_a_short_pointer_replaces_a_persistent_one_without_leaving_state(make_stack):
    s = await make_stack([])
    await s.session.highlight_ref(C1, persistent=True)
    await s.session.highlight_ref(C2, duration_ms=1500)  # a narration cue: brief
    assert s.session.active_highlight is None
    assert s.mock.highlight_log[-1] == (C2, 1500)


async def test_user_touching_the_highlight_ends_it(make_stack):
    s = await make_stack([])
    await s.session.highlight_ref(C1, persistent=True)
    assert s.session.active_highlight is not None
    await asyncio.to_thread(s.mock.simulate_user_touches_highlight)  # the adapter reports `highlight_dismissed`
    await _until(lambda: s.session.active_highlight is None)
    assert s.mock.highlight_active is None
    clears = s.mock.highlight_clears
    assert not await s.session.clear_highlight("tutor")  # already gone: no call to the adapter
    assert s.mock.highlight_clears == clears


async def test_a_highlight_nobody_ended_expires(make_stack, monkeypatch):
    monkeypatch.setattr(session_mod, "HIGHLIGHT_TTL_S", 0.1)
    s = await make_stack([])
    await s.session.highlight_ref(C1, persistent=True)
    await _until(lambda: s.mock.highlight_clears == 1)  # the Core forgets it, then tells the adapter
    assert s.session.active_highlight is None and s.mock.highlight_active is None


async def test_an_older_adapter_gets_a_long_timed_highlight_and_no_clear(make_stack):
    s = await make_stack([])
    s.session.conn.manifest.contract_version = "1.0.0"  # a 1.0 adapter knows neither duration 0 nor clearing
    await s.session.highlight_ref(C1, persistent=True)
    assert s.mock.highlight_log[-1] == (C1, session_mod.LEGACY_LONG_HIGHLIGHT_MS)
    assert s.session.active_highlight is None
    assert not await s.session.clear_highlight("tutor")
    assert s.mock.highlight_clears == 0


async def test_switching_application_takes_the_highlight_down(make_stack):
    s = await make_stack([])
    await s.session.highlight_ref(C1, persistent=True)
    conn = s.session.conn
    s.session._on_new_active(conn)  # what activating an application does
    await _until(lambda: s.session.active_highlight is None and s.mock.highlight_active is None)


async def test_a_cue_highlight_lasts_as_long_as_its_sentence(make_stack):
    s = await make_stack([])
    text = (
        "This is the folder that holds the gRPC entry points of the broker service and its mappers. " * 1
    )  # ~90 chars
    await s.session.narrate(text, cues=[{"at_word": 0, "op": "highlight", "target": C1}])
    seg = (await s.ui.wait_for(lambda m: m.get("type") == "narration.segment"))["segment"]
    await s.ui.send(type="narration.cue", segment_id=seg["id"], index=0)
    await _until(lambda: s.mock.highlight_log)
    ref, ms = s.mock.highlight_log[-1]
    expected = min(
        session_mod.CUE_MAX_MS, max(session_mod.CUE_MIN_MS, int(len(seg["text"]) * session_mod.CUE_MS_PER_CHAR))
    )
    assert ref == C1 and ms == expected and ms > session_mod.CUE_MIN_MS
    assert s.session.active_highlight is None  # a cue is brief: it never leaves state behind


async def test_a_failed_highlight_is_logged_for_diagnosis(make_stack):
    from wysp_core.contract import ErrorCode, WyspError

    s = await make_stack([])
    seen: list[tuple[str, dict]] = []
    real = s.session.tm.emit
    s.session.tm.emit = lambda kind, *a, **k: (seen.append((kind, k)), real(kind, *a, **k))[1]  # type: ignore[method-assign]

    def refuse(ref, style, duration_ms):
        raise WyspError(ErrorCode.TARGET_NOT_FOUND, "no such thing")

    s.mock.highlight = refuse
    assert not await s.session.highlight_ref(C1, persistent=True)
    assert any(kind == "highlight.failed" and "no such thing" in k.get("error", "") for kind, k in seen)
