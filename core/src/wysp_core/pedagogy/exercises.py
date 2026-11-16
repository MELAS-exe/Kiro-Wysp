"""The exercise engine: offers an exercise, counts attempts and hints, and turns a verified success into evidence.

Pure with respect to I/O: callers pass fresh observations in. That keeps the rules testable
(PED-P4 Wysp actions never count, PED-P5 no stale success, PED-P6 bindings, PED-P8 hints in order).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..contract import Evidence, Observation, PredicateOutcome
from ..contract.predicates import PredicateError, evaluate, substitute
from .learner import LearnerModel
from .lessons import Exercise, loc, resolve_bindings


def _leaves(outcomes: list[PredicateOutcome]) -> list[PredicateOutcome]:
    out: list[PredicateOutcome] = []
    for o in outcomes:
        out += _leaves(o.children) if o.children else [o]
    return out


def check_success(
    exercise: Exercise, obs: Observation, bindings: dict[str, str]
) -> tuple[bool, list[PredicateOutcome]]:
    """Evaluate the authored success predicate on an observation (never a cached one)."""
    outcome = evaluate(substitute(exercise.success, None, bindings), obs)
    return outcome.ok, [outcome]


@dataclass
class Refusal:
    reason: str


@dataclass
class Active:
    exercise: Exercise
    bindings: dict[str, str]
    start_version: int
    own_at_start: int
    passing_leaves: int = 0
    hints_used: int = 0
    attempts: int = 0
    status: str = "active"  # active | passed | failed | declared


@dataclass
class Result:
    status: str  # passed | failed | retry | declared | refused
    message: str = ""
    evidence: Evidence | None = None
    attempts: int = 0
    hints_used: int = 0
    failure: list[dict[str, Any]] = field(default_factory=list)


def _evidence(
    kind: str,
    source: str,
    active: Active,
    outcomes: list[PredicateOutcome],
    obs: Observation | None,
) -> Evidence:
    return Evidence(
        id=uuid.uuid4().hex[:10],
        type=kind,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        exercise_id=active.exercise.id,
        skills=list(active.exercise.skills),
        outcomes=outcomes,
        observation_id=obs.observation_id if obs else None,
        state_version=obs.state_version if obs else None,
        created_at=datetime.now(UTC).isoformat(),
        hints_used=active.hints_used,
    )


class ExerciseEngine:
    def __init__(self, learner: LearnerModel) -> None:
        self.learner = learner
        self.active: Active | None = None

    # ------------------------------------------------------------------------ offer
    def offer(
        self, exercise: Exercise, obs: Observation, context: dict[str, Any] | None = None, own_total: int = 0
    ) -> Active | Refusal:
        if exercise.success is None:
            return Refusal("this exercise has no success criteria")
        bindings = resolve_bindings(exercise.bindings, obs, context)
        if bindings is None:
            return Refusal("select the object or item the exercise is about first, then ask again")
        try:
            ok, outcomes = check_success(exercise, obs, bindings)
        except PredicateError as exc:
            return Refusal(f"the success criteria cannot be evaluated here ({exc})")
        if ok:
            return Refusal("it is already done in the application, so it would prove nothing; pick another exercise")
        self.active = Active(
            exercise=exercise,
            bindings=bindings,
            start_version=obs.state_version,
            own_at_start=own_total,
            passing_leaves=sum(1 for o in _leaves(outcomes) if o.ok),
        )
        return self.active

    # ------------------------------------------------------------------------ hints
    def next_hint(self, lang: str = "en") -> str | None:
        """The next hint, in authored order (PED-P8), or None when all were given."""
        a = self.active
        if a is None or a.status != "active" or a.hints_used >= len(a.exercise.hints):
            return None
        hint = loc(a.exercise.hints[a.hints_used], lang)
        a.hints_used += 1
        return hint

    # ---------------------------------------------------------------------- verify
    def evaluate(self, obs: Observation, origin: str, own_total: int, claim: bool = False) -> Result | None:
        """Check the exercise after a change. Only the learner's own changes count (PED-P4, PED-P5)."""
        a = self.active
        if a is None or a.status != "active":
            return None
        if origin != "user" and not claim:
            return None
        if claim and own_total != a.own_at_start:
            return Result("refused", "Wysp changed the application since the exercise began, so it cannot count.")
        if obs.state_version <= a.start_version:
            return Result("retry", "Nothing has changed in the application yet.") if claim else None
        try:
            ok, outcomes = check_success(a.exercise, obs, a.bindings)
        except PredicateError as exc:
            return Result("refused", f"The check could not run: {exc}")
        if ok:
            evidence = _evidence("verified", "core", a, outcomes, obs)
            a.status = "passed"
            self.learner.update(a.exercise.skills, True, "verified", evidence.id, a.hints_used)
            return Result("passed", "", evidence, a.attempts, a.hints_used)
        passing = sum(1 for o in _leaves(outcomes) if o.ok)
        if claim or passing < a.passing_leaves:
            a.attempts += 1  # a step that was right became wrong, or the learner said "done" too early
        a.passing_leaves = passing
        failure = [
            {"path": o.path, "op": o.op, "expected": o.expected, "actual": o.actual}
            for o in _leaves(outcomes)
            if not o.ok
        ][:3]
        if a.attempts >= a.exercise.max_attempts:
            evidence = _evidence("verified", "core", a, outcomes, obs)
            a.status = "failed"
            self.learner.update(a.exercise.skills, False, "verified", evidence.id, a.hints_used)
            return Result("failed", "", evidence, a.attempts, a.hints_used, failure)
        return Result("retry", "", None, a.attempts, a.hints_used, failure)

    def declare(self) -> Result:
        """The learner says it is done and the application cannot show it: weak evidence, labelled as such."""
        a = self.active
        if a is None or a.status != "active":
            return Result("refused", "There is no exercise in progress.")
        if a.exercise.verifiable:
            return Result("refused", "The application can verify this one: do it there and Wysp will see it.")
        evidence = _evidence("declared", "learner", a, [], None)
        a.status = "declared"
        self.learner.update(a.exercise.skills, True, "declared", evidence.id, a.hints_used)
        return Result("declared", "", evidence, a.attempts, a.hints_used)

    def view(self, lang: str = "en") -> dict[str, Any] | None:
        a = self.active
        if a is None:
            return None
        return {
            "exercise_id": a.exercise.id,
            "prompt": loc(a.exercise.prompt, lang),
            "skills": a.exercise.skills,
            "status": a.status,
            "attempts": a.attempts,
            "max_attempts": a.exercise.max_attempts,
            "hints_used": a.hints_used,
            "hints_total": len(a.exercise.hints),
        }
