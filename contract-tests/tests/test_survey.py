"""Survey of the application on activation [core-orchestrator 17]: CORE-P13, CORE-P14 and scenario tests."""

from __future__ import annotations

import asyncio
import time

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from wysp_core.contract import Entity, Observation, WyspError
from wysp_core.orchestrator.context import build_system_prompt
from wysp_core.session import survey as survey_mod
from wysp_core.session.survey import MAX_RENDER_CHARS, SurveyRunner, summarize

SECRET = "TOPSECRETLABEL"


async def _until(pred, timeout: float = 6.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


# ------------------------------------------------------------------------------------------ CORE-P13
async def test_prop_core_p13_survey_refs_are_observed_refs(make_stack):
    """CORE-P13: every surveyed ref is a recorded observed ref, and the survey follows activation."""
    s = await make_stack([])
    await _until(lambda: s.session.survey.current is not None)
    sv = s.session.survey.current
    assert sv.status == "ok" and sv.adapter_id == "mock-kanban"
    obs = await s.session.conn.observe(survey_mod.Scope(level="full"))
    assert obs.entities, "the mock adapter shows cards"
    assert {e.ref for e in obs.entities} <= s.session.observed_refs
    assert sv.counts and sv.action_ids


async def test_survey_reaches_the_prompt_and_the_panel(make_stack):
    s = await make_stack([])
    await _until(lambda: s.session.survey.current is not None)
    prompt = await build_system_prompt(s.session)
    assert "Survey of the application taken" in prompt
    assert "Counts per kind" in prompt
    # the Panel may join after the first survey: a refresh shows progress to it
    s.session.survey.start()
    await s.ui.wait_for(lambda m: m.get("type") == "activity" and m["text"].startswith("Surveying"))
    await s.ui.wait_for(lambda m: m.get("type") == "activity" and m["text"].startswith("Survey done"))
    texts = [m.get("text", "") for m in s.ui.of_type("activity")]
    assert any(t.startswith("Surveying") for t in texts)


# ------------------------------------------------------------------------------------------ CORE-P14
@st.composite
def observations(draw):
    n = draw(st.integers(0, 150))
    entities = []
    for i in range(n):
        sensitive = draw(st.booleans())
        label = draw(st.text(max_size=300))
        props = {"sensitive": True} if sensitive else {}
        if sensitive:
            label = SECRET + label
        entities.append(
            Entity(
                ref=f"x://e/{i}",
                kind=draw(st.sampled_from(["file", "dir", "thing", "problem"])),
                label=label,
                parent=(f"x://e/{draw(st.integers(0, i - 1))}" if i and draw(st.booleans()) else None),
                props=props,
            )
        )
    return Observation(
        observation_id="obs-1",
        state_version=1,
        captured_at="2026-11-13T00:00:00Z",
        entities=entities,
        truncated=draw(st.booleans()),
    )


@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
@given(observations())
def test_prop_core_p14_render_is_bounded_and_withholds_sensitive(obs):
    """CORE-P14: any observation renders within the bound; sensitive labels never appear."""
    text = summarize("a", obs, "full").render()
    assert len(text) <= MAX_RENDER_CHARS
    assert SECRET not in text
    if obs.truncated:
        assert "TRUNCATED" in text


async def test_prop_core_p14_slow_survey_delays_a_turn_at_most_the_bound(make_stack):
    s = await make_stack([])
    await _until(lambda: s.session.survey.current is not None)
    runner = s.session.survey
    runner._task = asyncio.create_task(asyncio.sleep(60))  # a survey that never finishes
    started = time.monotonic()
    await runner.wait(0.2)
    assert time.monotonic() - started < 1.0
    runner._task.cancel()


# ----------------------------------------------------------------------------------------- scenarios
async def test_survey_off_means_no_survey(make_stack, monkeypatch):
    monkeypatch.setenv("WYSP_SURVEY", "off")
    s = await make_stack([])
    await asyncio.sleep(0.4)
    assert s.session.survey.current is None and not s.session.survey.enabled
    assert "Survey of the application" not in await build_system_prompt(s.session)


async def test_state_change_refreshes_the_survey(make_stack, monkeypatch):
    monkeypatch.setattr(survey_mod, "STALE_DEBOUNCE_S", 0.05)
    s = await make_stack([])
    await _until(lambda: s.session.survey.current is not None)
    first = s.session.survey.current
    s.session.survey.mark_stale()
    assert first.stale
    await _until(lambda: s.session.survey.current is not first)
    assert not s.session.survey.current.stale


async def test_failed_survey_is_retried_then_succeeds(make_stack, monkeypatch):
    monkeypatch.setattr(survey_mod, "RETRY_DELAY_S", 0.05)
    s = await make_stack([])
    await _until(lambda: s.session.survey.current is not None)
    conn = s.session.conn
    real = conn.observe
    calls = {"n": 0}

    async def flaky(scope=None):
        calls["n"] += 1
        if calls["n"] <= 2:  # the full observation and the summary fallback both fail
            raise WyspError(-32016, "timeout")
        return await real(scope)

    conn.observe = flaky
    s.session.survey.current = None
    s.session.survey.start()
    await _until(lambda: s.session.survey.current is not None and s.session.survey.current.status == "ok")
    assert calls["n"] >= 3


def test_runner_is_inert_without_a_connection():
    class Dummy:
        conn = None

    runner = SurveyRunner(Dummy(), enabled=False)  # type: ignore[arg-type]
    runner.start()
    runner.mark_stale()
    assert runner.current is None and not runner.running
