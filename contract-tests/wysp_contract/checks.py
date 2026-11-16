"""Observation property checks of the Contract Test Kit [adapter-contract 9.1].

Each check talks to the adapter through one callable, `request(method, params) -> result` (raising `WyspError` for
a JSON-RPC error). The online harness will hand it a WebSocket round trip; the in-process mode and the tests hand it
`MockKanban.handle` or any other `AdapterRuntime.handle`. The checks depend on `wysp_core.contract` only.

    CON-P2   observe_integrity     refs unique, parent / link / focus refs resolve, every kind declared
    CON-P3   ref_stability         two observations without a change share refs and digest
    CON-P7   postconditions        after each safe call, its postconditions hold on a fresh observation
    CON-P10  size_limits           at most 500 entities and 256 KB, `counts` honest when truncated
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from wysp_core.contract import ActionSpec, Manifest, Observation, check_observation, digest
from wysp_core.contract.observation import MAX_ENTITIES, MAX_OBSERVATION_BYTES
from wysp_core.contract.predicates import PredicateError, evaluate, substitute

Request = Callable[[str, dict[str, Any]], Any]


@dataclass
class Finding:
    check: str
    ok: bool
    detail: str = ""

    def __str__(self) -> str:
        return f"{'PASS' if self.ok else 'FAIL'} {self.check}" + (f": {self.detail}" if self.detail else "")


def observe(request: Request, scope: dict[str, Any] | None = None) -> tuple[Observation, int]:
    """Return the validated observation and the size in bytes of its JSON form."""
    raw = request("adapter.observe", {"scope": scope or {"level": "full"}})
    return Observation.model_validate(raw), len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))


def size_problems(obs: Observation, size_bytes: int) -> list[str]:
    """CON-P10."""
    problems: list[str] = []
    if len(obs.entities) > MAX_ENTITIES:
        problems.append(f"{len(obs.entities)} entities exceed the limit of {MAX_ENTITIES}")
    if size_bytes > MAX_OBSERVATION_BYTES:
        problems.append(f"{size_bytes} bytes exceed the limit of {MAX_OBSERVATION_BYTES}")
    if obs.truncated:
        returned = Counter(e.kind for e in obs.entities)
        for kind, n in sorted(returned.items()):
            if obs.counts.get(kind, 0) < n:
                problems.append(f"truncated, but counts[{kind!r}]={obs.counts.get(kind, 0)} < {n} returned")
    return problems


def check_observe_integrity(request: Request, manifest: Manifest) -> Finding:
    """CON-P2 and CON-P10 on a full observation."""
    obs, size = observe(request)
    problems = check_observation(obs, manifest.kind_names) + size_problems(obs, size)
    return Finding("observe_integrity", not problems, "; ".join(problems))


def check_ref_stability(request: Request, manifest: Manifest) -> Finding:
    """CON-P3: observing twice with no change in between gives the same refs and the same digest."""
    first, _ = observe(request)
    second, _ = observe(request)
    volatile = manifest.volatile_props
    problems = []
    if {e.ref for e in first.entities} != {e.ref for e in second.entities}:
        problems.append("the set of refs changed between two observations without a change")
    if digest(first, volatile) != digest(second, volatile):
        problems.append("the digest changed between two observations without a change (undeclared volatile prop?)")
    return Finding("ref_stability", not problems, "; ".join(problems))


def check_postconditions(request: Request, calls: list[dict[str, Any]], undo: bool = True) -> Finding:
    """CON-P7: run each safe call, observe afresh, and evaluate the action's postconditions with placeholders
    substituted. Reversible calls are undone afterwards so that the next call starts from the same state."""
    specs = {s.id: s for s in (ActionSpec.model_validate(a) for a in request("adapter.get_actions", {}))}
    problems: list[str] = []
    for n, call in enumerate(calls):
        action_id, params = call["action_id"], call.get("params", {})
        spec = specs.get(action_id)
        if spec is None:
            problems.append(f"call {n}: unknown action {action_id!r}")
            continue
        try:
            result = request(
                "adapter.execute",
                {"call": {"action_id": action_id, "params": params, "request_id": f"kit-{n}", "dry_run": False}},
            )
        except Exception as exc:  # noqa: BLE001 - core and SDK each define a WyspError carrying code and message
            code = getattr(exc, "code", None)
            if code is None:
                raise
            problems.append(f"call {n} {action_id}: safe call failed with {code} {getattr(exc, 'message', exc)}")
            continue
        if result.get("status") != "ok":
            problems.append(f"call {n} {action_id}: status {result.get('status')!r}")
            continue
        obs, _ = observe(request)  # fresh, taken after the execute returned
        for post in spec.postconditions:
            try:
                outcome = evaluate(substitute(post, params), obs)
            except PredicateError as exc:
                problems.append(f"call {n} {action_id}: postcondition cannot be evaluated: {exc}")
                continue
            if not outcome.ok:
                problems.append(
                    f"call {n} {action_id}: postcondition failed (path={outcome.path} actual={outcome.actual})"
                )
        if undo and result.get("undo_token"):
            request("adapter.undo", {"token": result["undo_token"]})
    return Finding("postconditions", not problems, "; ".join(problems))


def run_observation_checks(
    request: Request, manifest: Manifest, safe_calls: list[dict[str, Any]] | None = None
) -> list[Finding]:
    findings = [check_observe_integrity(request, manifest), check_ref_stability(request, manifest)]
    findings.append(check_postconditions(request, safe_calls or []))
    return findings
