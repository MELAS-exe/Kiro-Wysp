"""Append-only audit log (JSONL) of everything the tutor proposes and does. Secrets are redacted."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..store import redact

MAX_FIELD_CHARS = 200


def _truncate(obj: Any) -> Any:
    """Keep audit records small and avoid persisting long free-text values (possibly sensitive)."""
    if isinstance(obj, str):
        return obj if len(obj) <= MAX_FIELD_CHARS else obj[:MAX_FIELD_CHARS] + f"…[+{len(obj) - MAX_FIELD_CHARS} chars]"
    if isinstance(obj, dict):
        return {k: _truncate(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_truncate(v) for v in obj]
    return obj


class AuditLog:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []  # in-memory copy, for tests and the Panel

    def append(self, kind: str, **fields: Any) -> dict[str, Any]:
        record = _truncate(redact({"ts": datetime.now(UTC).isoformat(), "kind": kind, **fields}))
        with self._lock:
            self.records.append(record)
            if self.directory is not None:
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
                with path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
