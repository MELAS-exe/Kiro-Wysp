"""Lessons and exercises end to end on the mock adapter [pedagogy-verification 4-7]: PED-P4, P5, P6 in a real session."""

from __future__ import annotations

import asyncio
import time

from wysp_core.orchestrator.tools import ToolBox, tool_specs
from wysp_core.pedagogy.lessons import Exercise, Lesson
from wysp_mock.kanban import card_ref

C2, C3 = card_ref("c2"), card_ref("c3")  # c2 is in "doing", c3 in "todo"


async def _until(pred, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


def _exercise(**over) -> Exercise:
    base = dict(
        id="move_c3",
        prompt={"en": "Move the card to Doing."},
        skills=["flow"],
        bindings={"card": f"$ref:{C3}"},
        success={
            "all": [{"path": "entities[?ref=='${bindings.card}'] | [0].props.column", "op": "eq", "value": "doing"}]
        },
        hints=[{"en": "Drag it."}, {"en": "Drop it on Doing."}],
        max_attempts=3,
    )
    base.update(over)
    return Exercise(**base)


async def _setup(make_stack, *exercises: Exercise):
    s = await make_stack([])
    t = s.session.tutoring
    t.lessons = [
        Lesson(
            id="kanban.flow",
            title="Flow",
            skills=["flow"],
            steps=[{"explain": {"en": "Cards move left to right."}}, {"check": {"exercise": "move_c3"}}],
            exercises=list(exercises),
        )
    ]
    return s, t, ToolBox(s.session)


async def test_a_user_change_is_verified_and_recorded_as_evidence(make_stack):
    s, t, box = await _setup(make_stack, _exercise())
    out = await box.call("start_exercise", {"exercise_id": "move_c3"})
    assert out["ok"] and out["prompt"] == "Move the card to Doing."
    before = t.learner.mastery("flow")

    s.mock.simulate_user("move_card", {"card": C3, "column": "doing"})  # the learner does it in the app
    ev = await s.ui.wait_for(lambda m: m.get("type") == "evidence.added" and m["scope"] == "exercise")
    assert ev["evidence"]["type"] == "verified" and ev["evidence"]["exercise_id"] == "move_c3"
    assert ev["evidence"]["outcomes"][0]["ok"] and ev["evidence"]["observation_id"]
    assert t.learner.mastery("flow") > before
    assert any(r.get("kind") == "exercise_result" and r["status"] == "passed" for r in s.audit)
    assert s.ui.of_type("exercise.update")[-1]["status"] == "passed"


async def test_changes_by_wysp_never_count(make_stack):
    s, t, box = await _setup(make_stack, _exercise())
    await box.call("start_exercise", {"exercise_id": "move_c3"})
    before = t.learner.mastery("flow")

    s.session.begin_own_change()  # an approved Wysp action is changing the application
    s.mock.cards["c3"]["column"] = "doing"
    s.mock.report_change([C3], origin="wysp")
    s.session.end_own_change()
    await asyncio.sleep(0.8)
    assert t.learner.mastery("flow") == before and not s.ui.of_type("evidence.added")
    assert t.engine.active.status == "active"

    # saying "I did it" does not turn Wysp's change into the learner's achievement either
    out = await box.call("check_exercise", {})
    assert out["status"] == "refused" and t.learner.mastery("flow") == before


async def test_no_stale_success_and_unresolved_targets_are_refused(make_stack):
    s, t, box = await _setup(
        make_stack,
        _exercise(),
        _exercise(id="done_already", bindings={"card": f"$ref:{C2}"}),
        _exercise(id="missing", bindings={"card": "$ref:mock://card/nope"}),
    )
    out = await box.call("start_exercise", {"exercise_id": "done_already"})
    assert not out["ok"] and "already done" in out["error"] and t.engine.active is None

    out = await box.call("start_exercise", {"exercise_id": "missing"})
    assert not out["ok"] and "select" in out["error"]

    await box.call("start_exercise", {"exercise_id": "move_c3"})
    out = await box.call("check_exercise", {})  # "done" before anything changed
    assert out["status"] == "retry" and not s.ui.of_type("evidence.added")


async def test_hints_in_order_cost_mastery_and_attempts_end_in_failure(make_stack):
    s, t, box = await _setup(make_stack, _exercise(max_attempts=2))
    await box.call("start_exercise", {"exercise_id": "move_c3"})
    assert (await box.call("exercise_hint", {}))["hint"] == "Drag it."
    assert (await box.call("exercise_hint", {}))["hint"] == "Drop it on Doing."
    assert not (await box.call("exercise_hint", {}))["ok"]

    s.mock.simulate_user("move_card", {"card": C2, "column": "done"})  # a change that is not the goal
    await asyncio.sleep(0.8)
    first = await box.call("check_exercise", {})
    second = await box.call("check_exercise", {})
    assert first["status"] == "retry" and second["status"] == "failed"
    assert t.learner.mastery("flow") < 0.2  # a verified failure lowers it


async def test_declared_evidence_only_for_exercises_the_app_cannot_verify(make_stack):
    s, t, box = await _setup(make_stack, _exercise(), _exercise(id="paper", verifiable=False))
    await box.call("start_exercise", {"exercise_id": "move_c3"})
    assert (await box.call("declare_done", {}))["status"] == "refused"

    await box.call("start_exercise", {"exercise_id": "paper"})
    out = await box.call("declare_done", {})
    assert out["status"] == "declared"
    ev = (await s.ui.wait_for(lambda m: m.get("type") == "evidence.added"))["evidence"]
    assert ev["type"] == "declared" and ev["source"] == "learner" and ev["outcomes"] == []


async def test_lesson_runner_tools_and_recommendation(make_stack):
    s, t, box = await _setup(make_stack, _exercise())
    status = await box.call("learner_status", {})
    assert status["recommended"] == "kanban.flow" and status["lessons"][0]["exercises"] == ["move_c3"]

    out = await box.call("lesson", {"action": "start", "lesson_id": "kanban.flow"})
    assert out["step"] == 1 and out["total"] == 2 and out["step_data"]["explain"] == "Cards move left to right."
    out = await box.call("lesson", {"action": "next"})
    assert out["step"] == 2
    out = await box.call("lesson", {"action": "next"})
    assert out["status"] == "done" and "kanban.flow" in t.learner.completed
    await s.ui.wait_for(lambda m: m.get("type") == "lesson.update" and m["status"] == "done")
    assert (await box.call("learner_status", {}))["recommended"] is None
    assert not (await box.call("lesson", {"action": "start", "lesson_id": "nope"}))["ok"]


async def test_the_tools_are_offered_by_capability(make_stack):
    names = {t.name for t in tool_specs({"observe"})}
    assert {"learner_status", "lesson", "exercise_hint", "declare_done", "start_exercise", "check_exercise"} <= names
    without = {t.name for t in tool_specs(set())}
    assert "start_exercise" not in without and "check_exercise" not in without and "lesson" in without


async def test_a_later_user_change_does_not_credit_a_goal_wysp_reached(make_stack):
    s, t, box = await _setup(make_stack, _exercise())
    await box.call("start_exercise", {"exercise_id": "move_c3"})
    s.session.begin_own_change()  # Wysp itself moves the card to the goal
    s.mock.cards["c3"]["column"] = "doing"
    s.mock.report_change([C3], origin="wysp")
    s.session.end_own_change()
    await asyncio.sleep(0.8)
    before = t.learner.mastery("flow")
    s.mock.simulate_user("move_card", {"card": C2, "column": "done"})  # an unrelated change by the learner
    await asyncio.sleep(0.8)
    assert t.learner.mastery("flow") == before and not s.ui.of_type("evidence.added")
    assert t.engine.active.status == "active"
