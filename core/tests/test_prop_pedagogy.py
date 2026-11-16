"""Pedagogy properties PED-P1 to P9 [pedagogy-verification 2-6]: pure functions, no adapter, no LLM."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml
from hypothesis import given
from hypothesis import strategies as st
from wysp_core.contract import Observation
from wysp_core.pedagogy.exercises import Active, ExerciseEngine, Refusal
from wysp_core.pedagogy.learner import ACQUIRED, WEIGHTS, LearnerModel, SkillState, bkt_update
from wysp_core.pedagogy.lessons import (
    Exercise,
    Lesson,
    LessonRunner,
    load_lessons,
    prerequisites_met,
    recommend,
    resolve_bindings,
    validate_lessons,
)

KINDS = list(WEIGHTS)
prob = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
hints = st.integers(min_value=0, max_value=12)


def obs(entities, focus=(), version=1) -> Observation:
    return Observation.model_validate(
        {
            "observation_id": f"o{version}",
            "state_version": version,
            "captured_at": datetime.now(UTC).isoformat(),
            "entities": entities,
            "focus": list(focus),
        }
    )


# --------------------------------------------------------------------------------- PED-P1 to P3
@given(st.lists(st.tuples(st.booleans(), st.sampled_from(KINDS), hints), max_size=60), prob)
def test_prop_ped_p1_mastery_is_bounded(events, prior):
    """PED-P1: for any sequence of evidence, mastery stays in [0, 1]."""
    p = prior
    for correct, kind, h in events:
        p = bkt_update(p, correct, kind, h)
        assert 0.0 <= p <= 1.0


@given(prob, hints)
def test_prop_ped_p2_correct_verified_never_lowers_mastery(prior, h):
    """PED-P2: a correct verified update gives p_new >= p."""
    assert bkt_update(prior, True, "verified", h) >= prior


@given(prob, hints)
def test_prop_ped_p3_evidence_strength_is_ordered(prior, h):
    """PED-P3: verified >= answered >= declared for a correct answer."""
    v, a, d = (bkt_update(prior, True, k, h) for k in ("verified", "answered", "declared"))
    assert v >= a >= d


# ------------------------------------------------------------------------------------- PED-P4, P5
def _engine(version=1):
    ex = Exercise(
        id="e1",
        prompt="Move c3",
        skills=["s1"],
        bindings={"card": "$ref:mock://card/c3"},
        success={
            "all": [{"path": "entities[?ref=='${bindings.card}'] | [0].props.column", "op": "eq", "value": "doing"}]
        },
        hints=["h1", "h2", "h3"],
        max_attempts=2,
    )
    learner = LearnerModel()
    engine = ExerciseEngine(learner)
    start = obs(
        [{"ref": "mock://card/c3", "kind": "card", "label": "c3", "props": {"column": "todo"}}], version=version
    )
    offer = engine.offer(ex, start)
    assert not isinstance(offer, Refusal)
    return engine, learner, ex


def _done(version):
    return obs(
        [{"ref": "mock://card/c3", "kind": "card", "label": "c3", "props": {"column": "doing"}}], version=version
    )


@given(st.sampled_from(["wysp", "unknown", ""]), st.integers(min_value=2, max_value=50))
def test_prop_ped_p4_wysp_actions_never_count(origin, version):
    """PED-P4: events that are not the user's never produce evidence or change mastery."""
    engine, learner, _ = _engine()
    before = learner.mastery("s1")
    assert engine.evaluate(_done(version), origin, own_total=0) is None
    assert learner.mastery("s1") == before and engine.active.status == "active"


@given(st.integers(min_value=0, max_value=1))
def test_prop_ped_p5_no_stale_success(version):
    """PED-P5: no pass without a user change after the start; an exercise satisfied at start is refused."""
    engine, learner, ex = _engine(version=1)
    assert engine.evaluate(_done(version), "user", own_total=0) is None  # same or older state: nothing new happened
    assert engine.active.status == "active"
    satisfied = ExerciseEngine(LearnerModel())
    assert isinstance(satisfied.offer(ex, _done(5)), Refusal)
    assert satisfied.active is None


def test_prop_ped_p5_a_user_change_after_the_start_passes():
    engine, learner, _ = _engine()
    res = engine.evaluate(_done(2), "user", own_total=0)
    assert res is not None and res.status == "passed" and res.evidence.type == "verified"
    assert learner.mastery("s1") > 0.2 and res.evidence.skills == ["s1"]


def test_claim_is_refused_when_wysp_changed_the_application():
    engine, learner, _ = _engine()
    res = engine.evaluate(_done(2), "user", own_total=1, claim=True)  # Wysp acted since the exercise began
    assert res.status == "refused" and engine.active.status == "active"


# ----------------------------------------------------------------------------------------- PED-P6
@given(
    st.lists(st.sampled_from(["a", "b", "c", "d"]), min_size=1, max_size=4, unique=True),
    st.sets(st.sampled_from(["a", "b", "c", "d"])),
)
def test_prop_ped_p6_offers_need_resolved_bindings(wanted, present):
    """PED-P6: an exercise is offered only if every binding resolves to an entity of the observation."""
    ex = Exercise(
        id="e",
        prompt="p",
        bindings={f"b_{w}": f"$ref:x://{w}" for w in wanted},
        success={"all": [{"path": "length(entities)", "op": "lt", "value": 0}]},
    )
    o = obs([{"ref": f"x://{p}", "kind": "k", "label": p} for p in sorted(present)])
    out = ExerciseEngine(LearnerModel()).offer(ex, o)
    if set(wanted) <= present:
        assert isinstance(out, Active)
    else:
        assert isinstance(out, Refusal)


def test_focus_binding_walks_up_to_the_nearest_ancestor_of_the_kind():
    o = obs(
        [
            {"ref": "x://obj", "kind": "object", "label": "o"},
            {"ref": "x://obj/mod", "kind": "modifier", "label": "m", "parent": "x://obj"},
        ],
        focus=["x://obj/mod"],
    )
    assert resolve_bindings({"t": "$focus.object"}, o) == {"t": "x://obj"}
    assert resolve_bindings({"t": "$focus.card"}, o) is None


# ----------------------------------------------------------------------------------------- PED-P7
skill_ids = st.lists(st.sampled_from(list("abcdef")), min_size=1, max_size=6, unique=True)


def _write_lessons(directory: Path, lessons: list[dict]) -> None:
    (directory / "lessons").mkdir(parents=True, exist_ok=True)
    for i, raw in enumerate(lessons):
        (directory / "lessons" / f"L{i:02d}.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")


@given(skill_ids, st.booleans(), st.booleans())
def test_prop_ped_p7_profile_validity(skills, bad_skill, cycle):
    """PED-P7: unknown references and prerequisite cycles are reported; valid lesson sets report nothing."""
    lessons = [
        {"id": "l1", "skills": [skills[0]], "prerequisites": []},
        {"id": "l2", "skills": [skills[-1]], "prerequisites": ["l1"]},
    ]
    if bad_skill:
        lessons[1]["skills"] = ["zzz_unknown"]
    if cycle:
        lessons[0]["prerequisites"] = ["l2"]
    with tempfile.TemporaryDirectory() as tmp:
        _write_lessons(Path(tmp), lessons)
        problems = validate_lessons(Path(tmp), set(skills))
    assert bool(problems) == (bad_skill or cycle)


def test_the_real_profiles_validate():
    root = Path(__file__).resolve().parents[2] / "apps"
    from wysp_core.pedagogy import validate_profile

    for tutor in ("blender-tutor", "intellij-tutor", "web-tutor"):
        assert validate_profile(root / tutor / "profile") == [], tutor
        assert load_lessons(root / tutor / "profile"), tutor


# ----------------------------------------------------------------------------------------- PED-P8
@given(st.integers(min_value=0, max_value=6), st.integers(min_value=0, max_value=12))
def test_prop_ped_p8_hints_come_in_order(n_hints, requests):
    """PED-P8: the revealed hints are a prefix of the authored list."""
    authored = [f"hint {i}" for i in range(n_hints)]
    engine = ExerciseEngine(LearnerModel())
    engine.active = Active(Exercise(id="e", prompt="p", hints=authored), {}, 0, 0)
    got = [h for h in (engine.next_hint() for _ in range(requests)) if h is not None]
    assert got == authored[: len(got)] and len(got) == min(n_hints, requests)


# ----------------------------------------------------------------------------------------- PED-P9
@st.composite
def curriculum(draw):
    n = draw(st.integers(min_value=1, max_value=7))
    skills = [f"s{i}" for i in range(4)]
    lessons = []
    for i in range(n):
        pool = skills + [lesson.id for lesson in lessons]
        pre = draw(st.lists(st.sampled_from(pool), max_size=3, unique=True))
        sk = draw(st.lists(st.sampled_from(skills), min_size=1, max_size=2, unique=True))
        lessons.append(Lesson(id=f"l{i}", title="t", skills=sk, prerequisites=pre))
    learner = LearnerModel()
    for s in skills:
        if draw(st.booleans()):
            learner.skills[s] = SkillState(draw(prob))
    learner.completed = draw(st.lists(st.sampled_from([lesson.id for lesson in lessons]), unique=True, max_size=n))
    return lessons, learner


@given(curriculum())
def test_prop_ped_p9_recommendation_respects_prerequisites(data):
    """PED-P9: a recommended lesson never has a non-acquired prerequisite, and is not already done."""
    lessons, learner = data
    pick = recommend(lessons, learner)
    if pick is None:
        return
    by_id = {x.id: x for x in lessons}
    assert pick.id not in learner.completed
    assert prerequisites_met(pick, by_id, learner)
    for pre in pick.prerequisites:
        assert (pre in learner.completed) if pre in by_id else (learner.mastery(pre) >= ACQUIRED)


# ------------------------------------------------------------------------------------ runner, store
def test_lesson_runner_state_machine():
    lesson = Lesson(id="l", title="t", steps=[{"explain": "a"}, {"explain": "b"}])
    r = LessonRunner()
    assert r.status == "idle" and r.current() is None
    r.start(lesson)
    assert r.summary()["step"] == 1 and r.current() == {"explain": "a"}
    r.repeat()
    assert r.index == 0
    r.skip()
    assert r.skipped == [0] and r.index == 1
    r.next()
    assert r.status == "done" and r.current() is None
    r.start(lesson)
    r.stop()
    assert r.status == "stopped"


def test_learner_file_survives_a_restart_and_corruption_is_backed_up(tmp_path):
    path = tmp_path / "learners" / "p.json"
    m = LearnerModel(path, priors={"a": 0.3})
    m.update(["a"], True, "verified", "ev1")
    m.complete("l1")
    again = LearnerModel(path, priors={"a": 0.3})
    assert again.mastery("a") == m.mastery("a") and again.completed == ["l1"]
    path.write_text("{not json", encoding="utf-8")
    broken = LearnerModel(path, priors={"a": 0.3})
    assert broken.mastery("a") == 0.3 and broken.warning
    assert path.with_suffix(".json.bak").exists()
