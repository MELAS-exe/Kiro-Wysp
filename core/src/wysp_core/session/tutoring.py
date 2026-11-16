"""Tutoring state of a session: lessons, the active exercise and the learner model.

The pedagogy package holds the rules; this class connects them to the session (fresh observations,
the audit log, the Panel). Everything that counts as the learner's achievement goes through here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..contract import Scope
from ..pedagogy import Profile
from ..pedagogy.exercises import Active, ExerciseEngine, Refusal, Result
from ..pedagogy.learner import LearnerModel, depth_hint
from ..pedagogy.lessons import Lesson, LessonRunner, loc, recommend, substitute_text
from ..store import wysp_home

if TYPE_CHECKING:
    from .session import Session

log = logging.getLogger("wysp.tutoring")


class Tutoring:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.lessons: list[Lesson] = []
        self.learner = LearnerModel()
        self.engine = ExerciseEngine(self.learner)
        self.runner = LessonRunner()
        self.profile: Profile | None = None

    def reset(self, profile: Profile | None) -> None:
        from ..pedagogy.lessons import load_lessons

        self.profile = profile
        self.lessons = load_lessons(profile.path) if profile else []
        priors = {str(s["id"]): float(s["prior"]) for s in (profile.skills if profile else []) if "prior" in s}
        params = {str(s["id"]): s["bkt"] for s in (profile.skills if profile else []) if isinstance(s.get("bkt"), dict)}
        path = wysp_home() / "learners" / f"{profile.id}.json" if profile else None
        self.learner = LearnerModel(path, priors, params)
        self.engine = ExerciseEngine(self.learner)
        self.runner = LessonRunner()

    # ------------------------------------------------------------------- reading
    def _exercise(self, exercise_id: str):
        for lesson in self.lessons:
            for ex in lesson.exercises:
                if ex.id == exercise_id:
                    return ex
        return None

    def status(self) -> dict[str, Any]:
        lang = self.s.lang
        skills = [str(s["id"]) for s in (self.profile.skills if self.profile else [])]
        nxt = recommend(self.lessons, self.learner)
        return {
            "ok": True,
            "skills": {
                sid: {
                    **info,
                    "title": loc(next((s.get("title") for s in self.profile.skills if s["id"] == sid), sid), lang),
                }
                for sid, info in self.learner.snapshot(skills).items()
            }
            if self.profile
            else {},
            "lessons": [
                {
                    "id": lesson.id,
                    "title": loc(lesson.title, lang),
                    "skills": lesson.skills,
                    "done": lesson.id in self.learner.completed,
                    "exercises": [e.id for e in lesson.exercises],
                }
                for lesson in self.lessons
            ],
            "recommended": nxt.id if nxt else None,
            "lesson": self.runner.summary(lang) if self.runner.lesson else None,
            "exercise": self.engine.view(lang),
            "warning": self.learner.warning,
        }

    # -------------------------------------------------------------------- lessons
    async def lesson(self, action: str, lesson_id: str | None) -> dict[str, Any]:
        lang = self.s.lang
        if action == "start":
            lesson = next((x for x in self.lessons if x.id == lesson_id), None)
            if lesson is None:
                return {"ok": False, "error": "unknown lesson; call learner_status to list them"}
            self.runner.start(lesson)
        elif action == "next":
            self.runner.next()
        elif action == "skip":
            self.runner.skip()
        elif action == "repeat":
            self.runner.repeat()
        elif action == "stop":
            self.runner.stop()
        else:
            return {"ok": False, "error": "action must be start, next, skip, repeat or stop"}
        if self.runner.status == "done" and self.runner.lesson:
            self.learner.complete(self.runner.lesson.id)
        await self.s.broadcast({"type": "lesson.update", **self.runner.summary(lang)})
        step = self.runner.current()
        out: dict[str, Any] = {"ok": True, **self.runner.summary(lang)}
        if self.runner.lesson:
            out["exercises"] = [e.id for e in self.runner.lesson.exercises]
        if step is not None:
            out["step_data"] = substitute_text(step, {}, lang)  # the model performs it; text only, not instructions
        self.s.audit.append("lesson", action=action, lesson_id=self.runner.lesson.id if self.runner.lesson else None)
        return out

    # ------------------------------------------------------------------ exercises
    async def start_exercise(self, exercise_id: str) -> dict[str, Any]:
        conn = self.s.conn
        ex = self._exercise(exercise_id)
        if ex is None:
            return {"ok": False, "error": "unknown exercise; call learner_status to list them"}
        if conn is None:
            return {"ok": False, "error": "no application is connected"}
        obs = await conn.observe(Scope(level="full"))
        offer = self.engine.offer(ex, obs, own_total=self.s.own_change_total)
        if isinstance(offer, Refusal):
            return {"ok": False, "refused": True, "error": offer.reason}
        self.s.audit.append("exercise_offered", exercise_id=ex.id, skills=ex.skills)
        await self._publish()
        return {
            "ok": True,
            "exercise_id": ex.id,
            "prompt": loc(ex.prompt, self.s.lang),
            "hints_available": len(ex.hints),
            "note": "Tell the learner what to do, then let them do it. Wysp checks the application by itself.",
        }

    async def hint(self) -> dict[str, Any]:
        hint = self.engine.next_hint(self.s.lang)
        if hint is None:
            return {"ok": False, "error": "no more hints, or no exercise in progress"}
        await self._publish()
        return {"ok": True, "hint": hint}

    async def check(self, claim: bool = True) -> dict[str, Any]:
        conn = self.s.conn
        if conn is None or self.engine.active is None:
            return {"ok": False, "error": "no exercise in progress"}
        obs = await conn.observe(Scope(level="full"))  # always fresh, never cached
        result = self.engine.evaluate(obs, "user", self.s.own_change_total, claim=claim)
        return await self._handle(result)

    async def declare(self) -> dict[str, Any]:
        return await self._handle(self.engine.declare())

    async def on_change(self, origin: str) -> None:
        """A change was reported by the application. Wysp's own changes are ignored (PED-P4)."""
        a = self.engine.active
        conn = self.s.conn
        if a is None or a.status != "active" or conn is None or origin != "user":
            return
        obs = await conn.observe(Scope(level="full"))
        await self._handle(self.engine.evaluate(obs, origin, self.s.own_change_total))

    # --------------------------------------------------------------------- shared
    async def _handle(self, result: Result | None) -> dict[str, Any]:
        if result is None:
            return {"ok": True, "status": "unchanged"}
        a: Active | None = self.engine.active
        title = loc(a.exercise.prompt, self.s.lang) if a else ""
        if result.evidence is not None:
            self.s.audit.append(
                "exercise_result",
                exercise_id=a.exercise.id if a else None,
                status=result.status,
                evidence_id=result.evidence.id,
                evidence_type=result.evidence.type,
            )
            await self.s.broadcast(
                {
                    "type": "evidence.added",
                    "evidence": result.evidence.model_dump(mode="json"),
                    "title": title,
                    "scope": "exercise",
                }
            )
        await self._publish()
        if result.status == "passed":
            await self.s.narrate(f"Verified in the application: {title}. Well done, you did that yourself.")
        elif result.status == "declared":
            await self.s.narrate("Noted. I could not check that one in the application, so it counts only a little.")
        out: dict[str, Any] = {"ok": result.status in ("passed", "declared", "retry"), "status": result.status}
        if result.message:
            out["message"] = result.message
        if result.failure:
            out["failing"] = result.failure
        out["attempts"] = result.attempts
        if a:
            out["mastery"] = {sk: round(self.learner.mastery(sk), 3) for sk in a.exercise.skills}
            out["depth"] = {sk: depth_hint(self.learner.mastery(sk)) for sk in a.exercise.skills}
        return out

    async def _publish(self) -> None:
        view = self.engine.view(self.s.lang)
        if view is not None:
            await self.s.broadcast({"type": "exercise.update", **view})
