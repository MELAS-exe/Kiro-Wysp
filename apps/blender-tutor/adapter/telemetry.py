"""Blender-side telemetry: one JSONL file per Blender session in ~/.wysp/logs/ (role "blender").

Same record shape as the Core's telemetry (``ts``, ``t_ms``, ``role``, ``session``, ``kind``, ``seq``), so
``wysp logs summary`` merges both by time. What is measured here is what the Core cannot see:

* ``request``    time a Core request waited for Blender's main thread (``queue_ms``) and ran (``run_ms``)
* ``slow_tick``  main-thread pump ticks longer than 50 ms (Blender was busy)
* ``observe``    how long building an observation took
* ``log``        warnings and errors of the ``wysp.*`` loggers (every line at level full)

Level: env ``WYSP_LOG`` wins, else the add-on preference. Never records tokens or field values typed by
the user; request parameters are not recorded at all.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEVELS = {"off": 0, "basic": 1, "full": 2}
SLOW_TICK_MS = 50.0


class AdapterTelemetry:
    def __init__(self) -> None:
        self.level = 0
        self.session = uuid.uuid4().hex[:10]
        self.path: Path | None = None
        self._fh = None
        self._lock = threading.Lock()
        self._seq = 0
        self._t0 = time.monotonic()

    def configure(self, level: str, directory: Path | None = None, meta: dict[str, Any] | None = None) -> None:
        level = (os.environ.get("WYSP_LOG") or level or "full").lower()
        self.level = LEVELS.get(level, 2)
        if not self.level:
            self.close()
            return
        if self._fh is None:
            d = directory or Path(os.environ.get("WYSP_HOME") or Path.home() / ".wysp") / "logs"
            try:
                d.mkdir(parents=True, exist_ok=True)
                self.path = d / f"blender-{datetime.now(UTC):%Y%m%d-%H%M%S}-{os.getpid()}.jsonl"
                self._fh = self.path.open("a", encoding="utf-8", newline="\n", buffering=1)
            except OSError:
                self._fh = None
                return
            self.emit("session.start", level=level, pid=os.getpid(), **(meta or {}))

    def enabled(self, level: str = "basic") -> bool:
        return self.level >= LEVELS[level] > 0

    def emit(self, kind: str, /, full: dict[str, Any] | None = None, **fields: Any) -> None:
        if not self.level or self._fh is None:
            return
        try:
            rec = {
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "t_ms": round((time.monotonic() - self._t0) * 1000, 1),
                "role": "blender",
                "session": self.session,
                "kind": kind,
                **fields,
            }
            if full and self.level >= LEVELS["full"]:
                rec.update(full)
            with self._lock:
                self._seq += 1
                rec["seq"] = self._seq
                self._fh.write(json.dumps(rec, ensure_ascii=False, default=str)[:8000] + "\n")
        except Exception:  # noqa: BLE001 - telemetry must never break Blender
            pass

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None


tm = AdapterTelemetry()


class _LogBridge(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING or tm.enabled("full"):
            tm.emit(
                "log",
                full={"message": record.getMessage()[:2000]},
                level_name=record.levelname,
                logger=record.name,
                summary=record.getMessage()[:160] if record.levelno >= logging.WARNING else None,
            )


_bridge = _LogBridge(level=logging.INFO)


def configure(level: str) -> None:
    meta: dict[str, Any] = {}
    try:
        import bpy

        meta = {"app_version": bpy.app.version_string, "background": bool(bpy.app.background)}
    except Exception:  # noqa: BLE001
        pass
    tm.configure(level, meta=meta)
    root = logging.getLogger("wysp")
    if _bridge not in root.handlers:
        root.addHandler(_bridge)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)


def close() -> None:
    logging.getLogger("wysp").removeHandler(_bridge)
    tm.close()


def on_request_done(info: dict[str, Any]) -> None:
    tm.emit("request", **info)
