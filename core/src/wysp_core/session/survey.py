"""Survey of the active application: look at everything the adapter can show before the tutor answers.

The survey only uses the existing adapter contract (`get_actions`, `get_context`, `observe`). It goes through
`Session.observe`, so every surveyed ref is recorded in `observed_refs` and an `observed` board node may point
at it. What the tutor reads is a bounded rendering (`Survey.render`), never the raw observation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..contract import Observation, Scope, WyspError

if TYPE_CHECKING:
    from .session import Session

log = logging.getLogger("wysp.survey")

MAX_RENDER_CHARS = 4000
MAX_STRUCTURE_LINES = 40
MAX_EXAMPLES_PER_KIND = 6
MAX_LABEL = 80
STALE_DEBOUNCE_S = 2.0
RETRY_DELAY_S = 5.0
MAX_RETRIES = 8
TURN_WAIT_S = 3.0


@dataclass
class Survey:
    adapter_id: str
    status: str = "ok"  # ok | partial | failed
    level: str = "full"
    observation_id: str | None = None
    state_version: int = 0
    captured_at: float = field(default_factory=time.monotonic)
    duration_ms: float = 0.0
    counts: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    stale: bool = False
    note: str | None = None
    summary: str = ""
    mode: str | None = None
    action_ids: list[str] = field(default_factory=list)
    structure: list[str] = field(default_factory=list)
    examples: dict[str, list[str]] = field(default_factory=dict)
    sensitive_counts: dict[str, int] = field(default_factory=dict)

    def render(self, max_chars: int = MAX_RENDER_CHARS) -> str:
        """A bounded text for the tutor. Sensitive entities are counted, never named."""
        age = max(0, int(time.monotonic() - self.captured_at))
        head = f"Survey of the application taken {age} s ago ({self.status}"
        head += ", out of date: the application changed since)" if self.stale else ")"
        lines = [head]
        if self.truncated:
            lines.append("The observation was TRUNCATED: lists below are not complete; say so, do not claim totals.")
        if self.status == "partial" and self.note:
            lines.append(f"Partial survey: {self.note}")
        if self.counts:
            lines.append("Counts per kind: " + ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items())))
        if self.sensitive_counts:
            lines.append(
                "Sensitive entities (names withheld): "
                + ", ".join(f"{k}={v}" for k, v in sorted(self.sensitive_counts.items()))
            )
        if self.structure:
            lines.append("Structure:")
            lines += self.structure
        for kind in sorted(self.examples):
            lines.append(f"Examples of {kind}: " + "; ".join(self.examples[kind]))
        if self.action_ids:
            lines.append("Actions available: " + ", ".join(self.action_ids))
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 40].rstrip() + "\n(survey cut to fit the context)"
        return text


def _clean(label: str) -> str:
    one = " ".join(str(label).split())
    return one if len(one) <= MAX_LABEL else one[: MAX_LABEL - 1] + "..."


def _is_sensitive(entity: Any) -> bool:
    return entity.props.get("sensitive") is True


def summarize(adapter_id: str, obs: Observation, level: str) -> Survey:
    """Pure function: an observation in, a bounded survey out. Property CORE-P14 is checked on it."""
    sv = Survey(
        adapter_id=adapter_id,
        level=level,
        observation_id=obs.observation_id,
        state_version=obs.state_version,
        truncated=obs.truncated,
    )
    counts: Counter[str] = Counter(e.kind for e in obs.entities)
    sv.counts = dict(obs.counts) if obs.counts else dict(counts)
    sensitive: Counter[str] = Counter(e.kind for e in obs.entities if _is_sensitive(e))
    sv.sensitive_counts = dict(sensitive)

    by_parent: dict[str | None, list[Any]] = {}
    refs = {e.ref for e in obs.entities}
    for e in obs.entities:
        parent = e.parent if e.parent in refs else None
        by_parent.setdefault(parent, []).append(e)

    def walk(parent: str | None, depth: int) -> None:
        for e in by_parent.get(parent, []):
            if len(sv.structure) >= MAX_STRUCTURE_LINES:
                return
            if _is_sensitive(e):
                continue
            kids = len(by_parent.get(e.ref, []))
            suffix = f" ({kids} inside)" if kids else ""
            sv.structure.append(f"{'  ' * (depth + 1)}- [{e.kind}] {_clean(e.label)}{suffix}")
            if depth < 1:  # roots and their direct children; the rest is reached through `observe`
                walk(e.ref, depth + 1)

    walk(None, 0)
    if len(sv.structure) >= MAX_STRUCTURE_LINES:
        sv.structure.append("  ...")

    for e in obs.entities:
        if _is_sensitive(e):
            continue
        bucket = sv.examples.setdefault(e.kind, [])
        if len(bucket) < MAX_EXAMPLES_PER_KIND:
            bucket.append(_clean(e.label))
    return sv


class SurveyRunner:
    """Owns the survey task of a session: start, wait for, refresh and retry."""

    def __init__(self, session: Session, enabled: bool = True) -> None:
        self.session = session
        self.enabled = enabled
        self.current: Survey | None = None
        self._task: asyncio.Task | None = None
        self._stale_task: asyncio.Task | None = None
        self._retries = 0

    # ------------------------------------------------------------------ control
    def reset(self) -> None:
        for t in (self._task, self._stale_task):
            if t is not None and not t.done():
                t.cancel()
        self.current = None
        self._retries = 0

    def start(self) -> None:
        """Start a survey of the active adapter in the background (no-op when disabled)."""
        if not self.enabled:
            return
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._run())

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def wait(self, timeout_s: float = TURN_WAIT_S) -> None:
        """Let a running survey finish, but never hold a turn longer than `timeout_s`."""
        task = self._task
        if task is None or task.done():
            return
        await asyncio.wait({task}, timeout=timeout_s)

    def mark_stale(self) -> None:
        """The application changed: refresh after a debounce."""
        if not self.enabled or self.current is None:
            return
        self.current.stale = True
        if self._stale_task is not None and not self._stale_task.done():
            self._stale_task.cancel()
        self._stale_task = asyncio.create_task(self._refresh_later())

    async def _refresh_later(self) -> None:
        try:
            await asyncio.sleep(STALE_DEBOUNCE_S)
        except asyncio.CancelledError:
            return
        if not self.running:
            self.start()

    # --------------------------------------------------------------------- work
    async def _run(self) -> None:
        s = self.session
        conn = s.conn
        if conn is None:
            return
        adapter_id = conn.adapter_id
        started = time.monotonic()
        await s.activity(f"Surveying {conn.manifest.app.name}...")
        survey = Survey(adapter_id=adapter_id, status="failed")
        try:
            survey = await self._survey(conn)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            survey.note = str(exc)[:200]
            log.exception("survey failed")
        survey.duration_ms = (time.monotonic() - started) * 1000
        if s.conn is None or s.conn.adapter_id != adapter_id:
            return  # the user switched application meanwhile
        self.current = survey
        s.tm.emit(
            "survey",
            adapter=adapter_id,
            status=survey.status,
            level=survey.level,
            duration_ms=round(survey.duration_ms, 1),
            counts=survey.counts,
            truncated=survey.truncated,
            observation_id=survey.observation_id,
            retries=self._retries,
        )
        if survey.status == "ok":
            self._retries = 0
            await s.activity(f"Survey done: {sum(survey.counts.values())} elements seen.")
        else:
            await s.activity("Survey incomplete, the tutor will look on demand.")
            if self._retries < MAX_RETRIES:
                self._retries += 1
                self._stale_task = asyncio.create_task(self._retry())

    async def _retry(self) -> None:
        try:
            await asyncio.sleep(
                min(60.0, RETRY_DELAY_S * 2 ** max(0, self._retries - 1))
            )  # 5, 10, 20, 40, 60 s: a slow start gets time
        except asyncio.CancelledError:
            return
        if not self.running:
            self.start()

    async def _survey(self, conn: Any) -> Survey:
        s = self.session
        actions: list[str] = []
        summary, mode = "", None
        try:
            actions = [a.id for a in await conn.get_actions(refresh=True)]
        except WyspError as exc:
            log.info("survey: actions unavailable: %s", exc.message)
        try:
            ctx = await conn.get_context()
            summary, mode = ctx.summary, ctx.mode
        except WyspError as exc:
            log.info("survey: context unavailable: %s", exc.message)
        level, note = "full", None
        try:
            obs = await s.observe(Scope(level="full"))
        except WyspError as exc:
            level, note = "summary", f"full observation failed ({exc.message}); summary only"
            try:
                obs = await s.observe(Scope(level="summary"))
            except WyspError as exc2:
                failed = Survey(adapter_id=conn.adapter_id, status="failed", summary=summary, mode=mode)
                failed.note = exc2.message[:200]
                failed.action_ids = actions
                return failed
        sv = summarize(conn.adapter_id, obs, level)
        sv.summary, sv.mode, sv.action_ids = summary, mode, actions
        if note:
            sv.status, sv.note = "partial", note
        return sv
