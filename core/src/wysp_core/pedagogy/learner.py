"""Learner model: a simplified Bayesian Knowledge Tracing (BKT) per skill.

Pure functions first (they carry the properties PED-P1 to P3), then a small JSON-backed store.
Only evidence about what the learner did counts: callers never pass actions that Wysp performed (PED-P4).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("wysp.learner")

SLIP, GUESS, TRANSIT = 0.1, 0.2, 0.15
WEIGHTS = {"verified": 1.0, "answered": 0.6, "declared": 0.3}
ACQUIRED = 0.85
DEFAULT_PRIOR = 0.2
HISTORY_LIMIT = 50


def clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def effective_weight(kind: str, hints_used: int = 0) -> float:
    """Evidence weight; every hint takes 15 % off, never below 40 % of the weight."""
    w = WEIGHTS[kind]
    return w * max(0.4, 1.0 - 0.15 * max(0, hints_used))


def bkt_update(
    p: float,
    correct: bool,
    kind: str = "verified",
    hints_used: int = 0,
    slip: float = SLIP,
    guess: float = GUESS,
    transit: float = TRANSIT,
) -> float:
    """New mastery after one piece of evidence. Always in [0, 1]; a correct answer never lowers it."""
    p = clamp(p)
    if correct:
        den = p * (1 - slip) + (1 - p) * guess
        posterior = p * (1 - slip) / den if den > 0 else p
    else:
        den = p * slip + (1 - p) * (1 - guess)
        posterior = p * slip / den if den > 0 else p
    bkt = posterior + (1 - posterior) * transit
    out = clamp(p + effective_weight(kind, hints_used) * (bkt - p))
    return max(out, p) if correct else out


def depth_hint(mastery: float) -> str:
    """How deep to teach, from the mastery thresholds of the tutoring strategy."""
    if mastery < 0.4:
        return "basics"
    if mastery < ACQUIRED:
        return "practice"
    return "challenge"


@dataclass
class SkillState:
    mastery: float
    history: list[str] = field(default_factory=list)  # last evidence ids


class LearnerModel:
    """Mastery per skill and the lessons completed, saved as JSON after every update."""

    def __init__(self, path: Path | None = None, priors: dict[str, float] | None = None, params: dict | None = None):
        self.path = path
        self.priors = priors or {}
        self.params = params or {}  # skill id -> {slip, guess, transit}
        self.skills: dict[str, SkillState] = {}
        self.completed: list[str] = []
        self.warning: str | None = None
        if path is not None:
            self._load()

    # ------------------------------------------------------------------ reading
    def mastery(self, skill: str) -> float:
        state = self.skills.get(skill)
        return state.mastery if state else clamp(self.priors.get(skill, DEFAULT_PRIOR))

    def acquired(self, skill: str) -> bool:
        return self.mastery(skill) >= ACQUIRED

    def snapshot(self, skills: list[str]) -> dict[str, dict[str, Any]]:
        return {s: {"mastery": round(self.mastery(s), 3), "depth": depth_hint(self.mastery(s))} for s in skills}

    # ----------------------------------------------------------------- updating
    def update(self, skills: list[str], correct: bool, kind: str, evidence_id: str, hints_used: int = 0) -> None:
        for skill in skills:
            extra = self.params.get(skill, {})
            new = bkt_update(
                self.mastery(skill),
                correct,
                kind,
                hints_used,
                slip=extra.get("slip", SLIP),
                guess=extra.get("guess", GUESS),
                transit=extra.get("transit", TRANSIT),
            )
            state = self.skills.setdefault(skill, SkillState(self.mastery(skill)))
            state.mastery = new
            state.history = [*state.history, evidence_id][-HISTORY_LIMIT:]
        self.save()

    def complete(self, lesson_id: str) -> None:
        if lesson_id not in self.completed:
            self.completed.append(lesson_id)
            self.save()

    # -------------------------------------------------------------- persistence
    def save(self) -> None:
        if self.path is None:
            return
        data = {
            "skills": {k: {"mastery": v.mastery, "history": v.history} for k, v in self.skills.items()},
            "completed": self.completed,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".learner-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("could not save the learner model")
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _load(self) -> None:
        assert self.path is not None
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            skills = {
                str(k): SkillState(clamp(float(v["mastery"])), [str(h) for h in v.get("history", [])][-HISTORY_LIMIT:])
                for k, v in raw["skills"].items()
            }
            completed = [str(c) for c in raw.get("completed", [])]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            self.warning = "The learner file was unreadable: starting from the priors (a backup was kept)."
            log.warning(self.warning)
            return
        self.skills, self.completed = skills, completed
