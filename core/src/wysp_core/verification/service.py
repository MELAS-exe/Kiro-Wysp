"""Verification: evaluate predicates on a FRESH observation and produce evidence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..contract import Evidence, Observation, PredicateOutcome, Scope
from ..contract.predicates import PredicateError, evaluate, substitute
from ..gateway.connection import AdapterConnection


@dataclass
class VerificationResult:
    ok: bool
    outcomes: list[PredicateOutcome]
    observation: Observation | None
    error: str | None = None

    def evidence(self, kind: str = "verified", **fields: Any) -> Evidence:
        return Evidence(
            id=uuid.uuid4().hex[:10],
            type=kind,  # type: ignore[arg-type]
            source="core",
            outcomes=self.outcomes,
            observation_id=self.observation.observation_id if self.observation else None,
            state_version=self.observation.state_version if self.observation else None,
            created_at=datetime.now(UTC).isoformat(),
            **fields,
        )

    def failure_summary(self) -> str:
        bad = [o for o in _leaves(self.outcomes) if not o.ok]
        if self.error:
            return self.error
        return "; ".join(f"{o.path}: expected {o.op} {o.expected!r}, found {o.actual!r}" for o in bad[:3]) or "unknown"


def _leaves(outcomes: list[PredicateOutcome]) -> list[PredicateOutcome]:
    out: list[PredicateOutcome] = []
    for o in outcomes:
        out += _leaves(o.children) if o.children else [o]
    return out


async def verify(
    conn: AdapterConnection,
    predicates: list[Any],
    params: dict[str, Any] | None = None,
    bindings: dict[str, Any] | None = None,
) -> VerificationResult:
    """Observe again (never use a cached observation) and evaluate every predicate."""
    try:
        concrete = [substitute(p, params, bindings) for p in predicates]
    except PredicateError as exc:
        return VerificationResult(False, [], None, f"cannot evaluate: {exc}")
    obs = await conn.observe(Scope(level="full"))
    try:
        outcomes = [evaluate(p, obs) for p in concrete]
    except PredicateError as exc:
        return VerificationResult(False, [], obs, f"cannot evaluate: {exc}")
    return VerificationResult(all(o.ok for o in outcomes), outcomes, obs)
