"""Lessons, exercises, binding resolution, recommendations and the lesson runner state machine.

Everything here is pure (no I/O besides reading the lesson files), so the correctness properties
PED-P6 to P9 are tested directly. Success criteria are authored predicates; the model never invents them.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..contract import Observation
from ..contract.predicates import PLACEHOLDER_RE, PredicateError, parse
from .learner import LearnerModel

DEFAULT_MAX_ATTEMPTS = 3


def loc(value: Any, lang: str = "en") -> str:
    """A localized text: a plain string or a {lang: text} map."""
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or next(iter(value.values()), ""))
    return "" if value is None else str(value)


@dataclass
class Exercise:
    id: str
    prompt: Any
    skills: list[str] = field(default_factory=list)
    bindings: dict[str, str] = field(default_factory=dict)
    success: Any = None
    hints: list[Any] = field(default_factory=list)
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    verifiable: bool = True  # False: the application cannot show it, the learner may declare it done
    lesson_id: str | None = None


@dataclass
class Lesson:
    id: str
    title: Any
    skills: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)  # skill ids or lesson ids
    board: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    exercises: list[Exercise] = field(default_factory=list)
    file: str = ""


def _exercise(raw: dict[str, Any], lesson_id: str | None) -> Exercise:
    return Exercise(
        id=str(raw["id"]),
        prompt=raw.get("prompt", ""),
        skills=[str(s) for s in raw.get("skills", []) or []],
        bindings={str(k): str(v) for k, v in (raw.get("bindings") or {}).items()},
        success={"all": raw["success"]} if isinstance(raw.get("success"), list) else raw.get("success"),
        hints=list(raw.get("hints", []) or []),
        max_attempts=int(raw.get("max_attempts", DEFAULT_MAX_ATTEMPTS)),
        verifiable=bool(raw.get("verifiable", True)),
        lesson_id=lesson_id,
    )


def load_lessons(directory: Path | None) -> list[Lesson]:
    """Every lessons/*.yaml of a profile directory, in file-name order. Unreadable files are skipped."""
    if directory is None or not (directory / "lessons").is_dir():
        return []
    lessons: list[Lesson] = []
    for path in sorted((directory / "lessons").glob("*.y*ml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            lid = str(raw["id"])
            lessons.append(
                Lesson(
                    id=lid,
                    title=raw.get("title", lid),
                    skills=[str(s) for s in raw.get("skills", []) or []],
                    prerequisites=[str(s) for s in raw.get("prerequisites", []) or []],
                    board=raw.get("board") or {},
                    steps=list(raw.get("steps", []) or []),
                    exercises=[_exercise(e, lid) for e in raw.get("exercises", []) or []],
                    file=path.name,
                )
            )
        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError):
            continue
    return lessons


# ---------------------------------------------------------------------------------- validation
def validate_lessons(directory: Path, skill_ids: set[str]) -> list[str]:
    problems: list[str] = []
    lessons_dir = directory / "lessons"
    if not lessons_dir.is_dir():
        return problems
    files = sorted(lessons_dir.glob("*.y*ml"))
    lessons = load_lessons(directory)
    if len(lessons) != len(files):
        problems.append("lessons: a lesson file is unreadable or has no 'id'")
    ids = [lesson.id for lesson in lessons]
    if len(ids) != len(set(ids)):
        problems.append("lessons: duplicate lesson ids")
    known_lessons = set(ids)
    graph: dict[str, list[str]] = {}
    exercise_ids: list[str] = []
    for lesson in lessons:
        where = f"lessons/{lesson.file}"
        for s in lesson.skills:
            if s not in skill_ids:
                problems.append(f"{where}: unknown skill '{s}'")
        for pre in lesson.prerequisites:
            if pre not in skill_ids and pre not in known_lessons:
                problems.append(f"{where}: unknown prerequisite '{pre}'")
        graph[lesson.id] = [p for p in lesson.prerequisites if p in known_lessons]
        for ex in lesson.exercises:
            exercise_ids.append(ex.id)
            ewhere = f"{where}: exercise '{ex.id}'"
            if not ex.prompt:
                problems.append(f"{ewhere} has no prompt")
            for s in ex.skills:
                if s not in skill_ids:
                    problems.append(f"{ewhere} has unknown skill '{s}'")
            if ex.success is None:
                problems.append(f"{ewhere} has no success criteria")
                continue
            try:
                parse(_strip_placeholders(ex.success))
            except PredicateError as exc:
                problems.append(f"{ewhere}: {exc}")
            used = set(re.findall(r"\$\{bindings\.([A-Za-z_]\w*)\}", yaml.safe_dump(ex.success)))
            for name in sorted(used - set(ex.bindings)):
                problems.append(f"{ewhere} uses undeclared binding '{name}'")
    if len(exercise_ids) != len(set(exercise_ids)):
        problems.append("lessons: duplicate exercise ids")

    def cyclic(node: str, seen: tuple[str, ...]) -> bool:
        return node in seen or any(cyclic(n, (*seen, node)) for n in graph.get(node, []))

    if any(cyclic(n, ()) for n in graph):
        problems.append("lessons: prerequisites contain a cycle")
    return problems


def _strip_placeholders(predicate: Any) -> Any:
    """Predicates are validated with placeholders replaced by a harmless literal."""
    text = yaml.safe_dump(predicate)
    text = PLACEHOLDER_RE.sub("x", text)
    return yaml.safe_load(text)


# --------------------------------------------------------------------------------------- bindings
def resolve_bindings(
    bindings: dict[str, str], obs: Observation, context: dict[str, Any] | None = None
) -> dict[str, str] | None:
    """Resolve each binding on an observation, or None when any of them cannot be (PED-P6).

    `$focus.<kind>`: the first focused entity of that kind, else its nearest ancestor of that kind.
    `$ref:<ref>`: a literal ref that must be in the observation. `$context.<fact>`: a context fact.
    """
    by_ref = {e.ref: e for e in obs.entities}
    out: dict[str, str] = {}
    for name, spec in bindings.items():
        value: str | None = None
        if spec.startswith("$focus."):
            kind = spec[len("$focus.") :]
            for ref in obs.focus:
                cur = by_ref.get(ref)
                while cur is not None:
                    if cur.kind == kind:
                        value = cur.ref
                        break
                    cur = by_ref.get(cur.parent) if cur.parent else None
                if value:
                    break
        elif spec.startswith("$context."):
            fact = (context or {}).get(spec[len("$context.") :])
            value = None if fact is None else str(fact)
        else:
            ref = spec[len("$ref:") :] if spec.startswith("$ref:") else spec
            value = ref if ref in by_ref else None
        if value is None:
            return None
        out[name] = value
    return out


# -------------------------------------------------------------------------------------- rendering
def substitute_text(value: Any, bindings: dict[str, str], lang: str) -> Any:
    """Localize a step and fill `${bindings.x}` in its strings."""
    if isinstance(value, dict) and value and set(value) <= {"en", "fr", "de", "es", "it"}:
        value = loc(value, lang)
    if isinstance(value, str):
        return PLACEHOLDER_RE.sub(
            lambda m: bindings.get(m.group(2), m.group(0)) if m.group(1) == "bindings" else m.group(0), value
        )
    if isinstance(value, list):
        return [substitute_text(v, bindings, lang) for v in value]
    if isinstance(value, dict):
        return {k: substitute_text(v, bindings, lang) for k, v in value.items()}
    return value


# -------------------------------------------------------------------------------- recommendations
def prerequisites_met(lesson: Lesson, lessons: dict[str, Lesson], learner: LearnerModel) -> bool:
    for pre in lesson.prerequisites:
        if pre in lessons:
            if pre not in learner.completed:
                return False
        elif not learner.acquired(pre):
            return False
    return True


def recommend(lessons: list[Lesson], learner: LearnerModel) -> Lesson | None:
    """The next lesson: prerequisites acquired, not done, something left to learn; weakest skills first (PED-P9)."""
    by_id = {lesson.id: lesson for lesson in lessons}
    best: tuple[float, int, Lesson] | None = None
    for order, lesson in enumerate(lessons):
        if lesson.id in learner.completed or not prerequisites_met(lesson, by_id, learner):
            continue
        if lesson.skills and all(learner.acquired(s) for s in lesson.skills):
            continue
        mean = sum(learner.mastery(s) for s in lesson.skills) / len(lesson.skills) if lesson.skills else 0.0
        if best is None or (mean, order) < (best[0], best[1]):
            best = (mean, order, lesson)
    return best[2] if best else None


# ------------------------------------------------------------------------------------- the runner
class LessonRunner:
    """idle -> running(step i) -> done | stopped. The model performs each step; the runner only keeps the place."""

    def __init__(self) -> None:
        self.lesson: Lesson | None = None
        self.index = 0
        self.status = "idle"
        self.skipped: list[int] = []

    def start(self, lesson: Lesson) -> None:
        self.lesson, self.index, self.skipped = lesson, 0, []
        self.status = "running" if lesson.steps else "done"

    @property
    def total(self) -> int:
        return len(self.lesson.steps) if self.lesson else 0

    def current(self) -> dict[str, Any] | None:
        if self.lesson is None or self.status != "running":
            return None
        return copy.deepcopy(self.lesson.steps[self.index])

    def next(self) -> None:
        if self.status != "running":
            return
        self.index += 1
        if self.index >= self.total:
            self.status = "done"

    def skip(self) -> None:
        if self.status == "running":
            self.skipped.append(self.index)
            self.next()

    def repeat(self) -> None:
        """Stay on the current step (the model explains it again)."""

    def stop(self) -> None:
        if self.status == "running":
            self.status = "stopped"

    def summary(self, lang: str = "en") -> dict[str, Any]:
        return {
            "lesson_id": self.lesson.id if self.lesson else None,
            "title": loc(self.lesson.title, lang) if self.lesson else None,
            "status": self.status,
            "step": min(self.index + 1, self.total) if self.lesson else 0,
            "total": self.total,
        }
