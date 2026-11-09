"""Session telemetry: structured JSONL logs plus in-memory performance aggregates.

Three levels, switchable at any time (env WYSP_LOG, `wysp serve --log`, the Panel or an adapter-hosted panel):

* ``off``   nothing is recorded.
* ``basic`` events, timings, counts and errors. No conversation text, no prompts, no tool arguments.
* ``full``  everything needed to replay and analyse a session: user messages, narration, prompts,
            model replies, tool arguments and results, adapter payload summaries, tracebacks.

Records are one JSON object per line in ``~/.wysp/logs/``. Secrets are redacted before writing.
Telemetry never raises: a logging problem must not break a tutoring session.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
import traceback
import uuid
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..store import redact

LEVELS = {"off": 0, "basic": 1, "full": 2}
MAX_SAMPLES = 4000
MAX_FIELD_CHARS = 4000
RING = 600


def _clip(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"…[+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(v, limit) for v in value[:200]]
    return value


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = max(0, min(len(ordered) - 1, round((p / 100) * (len(ordered) - 1))))
    return ordered[k]


class Telemetry:
    def __init__(
        self,
        level: str = "basic",
        directory: Path | None = None,
        role: str = "core",
        session_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.role = role
        self.session_id = session_id or uuid.uuid4().hex[:10]
        self.directory = directory
        self.meta = meta or {}
        self._level = LEVELS.get(level, 1)
        self._lock = threading.Lock()
        self._fh = None
        self._seq = 0
        self._t0 = time.monotonic()
        self._started = datetime.now(UTC)
        self.path: Path | None = None
        self.ring: deque[dict[str, Any]] = deque(maxlen=RING)
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=MAX_SAMPLES))
        self._counts: dict[str, int] = defaultdict(int)
        self._errors: dict[str, int] = defaultdict(int)
        if self._level:
            self.emit("session.start", role=role, **self.meta)

    # ----------------------------------------------------------------------------- level
    @property
    def level(self) -> str:
        return next(k for k, v in LEVELS.items() if v == self._level)

    def set_level(self, level: str) -> None:
        if level not in LEVELS or LEVELS[level] == self._level:
            return
        previous = self.level
        self._level = LEVELS[level]
        if self._level:
            self.emit("log.level", previous=previous, level=level, path=str(self.path) if self.path else None)
        elif self._fh:
            self.close()

    def enabled(self, level: str = "basic") -> bool:
        return self._level >= LEVELS[level] > 0

    # ---------------------------------------------------------------------------- output
    def _open(self) -> None:
        if self._fh is not None or self.directory is None:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            name = f"{self.role}-{self._started:%Y%m%d-%H%M%S}-{self.session_id}.jsonl"
            self.path = self.directory / name
            self._fh = self.path.open("a", encoding="utf-8", newline="\n", buffering=1)
        except OSError:
            self._fh = None

    def emit(self, kind: str, /, full: dict[str, Any] | None = None, **fields: Any) -> None:
        """Record an event. `fields` go to every level >= basic; `full` only to level full."""
        if not self._level:
            return
        try:
            record: dict[str, Any] = {
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "t_ms": round((time.monotonic() - self._t0) * 1000, 1),
                "role": self.role,
                "session": self.session_id,
                "kind": kind,
                **fields,
            }
            if full and self._level >= LEVELS["full"]:
                record.update(full)
            record = _clip(redact(record))
            duration = record.get("duration_ms")
            with self._lock:
                self._seq += 1
                record["seq"] = self._seq
                self._counts[kind] += 1
                if record.get("ok") is False or record.get("error"):
                    self._errors[kind] += 1
                if isinstance(duration, (int, float)):
                    self._samples[kind].append(float(duration))
                self.ring.append(record)
                self._open()
                if self._fh is not None:
                    self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:  # noqa: BLE001 - telemetry must never break the app
            pass

    @contextmanager
    def span(self, kind: str, /, full: dict[str, Any] | None = None, **fields: Any) -> Iterator[dict[str, Any]]:
        """Time a block. The body may add fields (``extra["x"] = 1``) and ``extra_full`` entries before it ends."""
        extra: dict[str, Any] = {}
        started = time.monotonic()
        try:
            yield extra
        except BaseException as exc:
            extra.setdefault("ok", False)
            extra.setdefault("error", f"{type(exc).__name__}: {exc}"[:300])
            raise
        finally:
            extra.setdefault("ok", True)
            more_full = extra.pop("_full", None)
            self.emit(
                kind,
                full={**(full or {}), **(more_full or {})} or None,
                duration_ms=round((time.monotonic() - started) * 1000, 1),
                **fields,
                **extra,
            )

    # -------------------------------------------------------------------------- metrics
    def metrics(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "level": self.level,
            "session": self.session_id,
            "path": str(self.path) if self.path else None,
            "timings": {},
        }
        with self._lock:
            for kind, samples in self._samples.items():
                s = list(samples)
                out["timings"][kind] = {
                    "n": len(s),
                    "p50_ms": round(percentile(s, 50), 1),
                    "p95_ms": round(percentile(s, 95), 1),
                    "max_ms": round(max(s), 1),
                    "mean_ms": round(statistics.fmean(s), 1),
                    "errors": self._errors.get(kind, 0),
                }
            out["counts"] = dict(self._counts)
        return out

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None


class TelemetryLogHandler(logging.Handler):
    """Bridges the existing `wysp.*` Python loggers into telemetry (warnings and errors at basic, info at full)."""

    def __init__(self, telemetry: Telemetry) -> None:
        super().__init__(level=logging.INFO)
        self.tm = telemetry

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno >= logging.WARNING or self.tm.enabled("full"):
                full: dict[str, Any] = {"message": record.getMessage()}
                if record.exc_info:
                    full["traceback"] = "".join(traceback.format_exception(*record.exc_info))
                self.tm.emit(
                    "log",
                    full=full,
                    level_name=record.levelname,
                    logger=record.name,
                    summary=record.getMessage()[:160] if record.levelno >= logging.WARNING else None,
                    has_exception=bool(record.exc_info),
                )
        except Exception:  # noqa: BLE001
            pass


def from_env(
    env: dict[str, str] | None = None,
    directory: Path | None = None,
    role: str = "core",
    meta: dict[str, Any] | None = None,
    level_override: str | None = None,
) -> Telemetry:
    import os

    env = dict(os.environ) if env is None else env
    level = (level_override or env.get("WYSP_LOG") or "full").lower()
    if level not in LEVELS:
        level = "full"
    return Telemetry(level=level, directory=directory, role=role, meta=meta)
