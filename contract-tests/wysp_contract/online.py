"""The online run of the Contract Test Kit [adapter-contract 9]: launch the tutor, connect, check, report.

    run_online(fixture, options) -> Report

Checks, in order (each is one JUnit test case; a fixture `skip` entry turns one into a skip):

    connect              the adapter said hello with the right token within the timeout
    manifest             valid, contract major, declares what the fixture expects, capabilities fit the actions
    context              adapter.get_context validates and stays under 8 KB
    observe_integrity    CON-P2, CON-P10   refs unique and resolvable, kinds declared, size limits
    ref_stability        CON-P3            two observations without a change share refs and digest
    min_entities         the fixture's minimum number of entities
    action_catalog       the catalog is exactly `expect.actions`, specs are coherent, no code-running actions
    postconditions       CON-P7            after each safe call, its postconditions hold
    undo_round_trip      CON-P6            undo restores the state digest
    dry_run              dry-run calls change nothing and return no undo token
    invalid_calls        CON-P5            expected error code, state digest unchanged
    state_version        CON-P8            monotonic, never behind the result of the call that preceded it
    events               payloads validate; CON-P9 nothing caused by Wysp is tagged `user`
    highlight            adapter.highlight (and the persistent form for contract 1.1)
    latency              every request stayed within its contract budget (plus the Core's slack)
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from wysp_core.contract import (
    ActionResult,
    ActionSpec,
    Context,
    HighlightDismissed,
    Manifest,
    Navigation,
    Observation,
    SelectionChanged,
    StateChanged,
    UserAction,
    WyspError,
    digest,
)
from wysp_core.contract.rpc import CONTRACT_VERSION, split_version

from . import launch as launchers
from .checks import (
    Finding,
    check_observe_integrity,
    check_ref_stability,
    check_safe_calls,
    observe,
)
from .fixture import Call, Fixture
from .harness import Event, Harness

EVENT_MODELS: dict[str, type] = {
    "event.state_changed": StateChanged,
    "event.selection_changed": SelectionChanged,
    "event.user_action": UserAction,
    "event.navigation": Navigation,
    "event.highlight_dismissed": HighlightDismissed,
}
CODE_RUNNING_ACTION = re.compile(r"(^|_)(exec|eval|shell|bash|script|python|js|javascript|run_code|run_command)(_|$)")
MAX_CONTEXT_BYTES = 8 * 1024
SETTLE_S = 1.0  # wait for debounced events after the last safe call
CAPABILITIES_REQUIRED = ("observe", "context", "actions")


@dataclass
class Options:
    timeout_s: float | None = None  # overrides launch.connect_timeout_s
    token: str | None = None
    faults: list[str] = field(default_factory=list)
    port: int = 0
    say: Callable[[str], None] = print


@dataclass
class Report:
    tutor: str
    findings: list[Finding] = field(default_factory=list)
    recording: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return bool(self.findings) and all(f.ok or f.skipped for f in self.findings)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)


def _timed(
    report: Report, fixture: Fixture, name: str, run: Callable[[], list[Finding] | Finding], also: tuple[str, ...] = ()
) -> None:
    """Run one check; a fixture `skip`, an exception, or the check's own result becomes a finding.
    `also`: further findings the same run produces (skipped together with `name`)."""
    if (reason := fixture.skipped(name)) is not None:
        for skipped_name in (name, *also):
            report.add(Finding(skipped_name, True, reason, skipped=True))
        return
    started = time.monotonic()
    try:
        out = run()
    except WyspError as exc:
        out = Finding(name, False, f"adapter error {exc.code}: {exc.message}")
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        out = Finding(name, False, f"{type(exc).__name__}: {str(exc)[:300]}")
    for finding in out if isinstance(out, list) else [out]:
        finding.seconds = round(time.monotonic() - started, 3)
        report.add(finding)


def _calls(items: list[Call], substitutions: dict[str, str]) -> list[dict[str, Any]]:
    out = [c.model_dump(exclude_none=True) for c in items]
    for old, new in substitutions.items():
        out = launchers.rewrite(out, old, new)
    return out


def state_digest(request: Callable[..., Any], manifest: Manifest) -> str:
    return digest(observe(request)[0], manifest.volatile_props)


# --------------------------------------------------------------------------------------- the checks


def check_manifest(fixture: Fixture, manifest: Manifest, specs: list[ActionSpec]) -> Finding:
    problems: list[str] = []
    if split_version(manifest.contract_version)[0] != split_version(CONTRACT_VERSION)[0]:
        problems.append(f"contract_version {manifest.contract_version} is not compatible with {CONTRACT_VERSION}")
    for capability in CAPABILITIES_REQUIRED:
        if not manifest.has(capability):
            problems.append(f"required capability '{capability}' is not declared")
    if any(s.reversible for s in specs) and not manifest.has("undo"):
        problems.append("some actions are reversible but the capability 'undo' is not declared")
    if specs and not manifest.has("execute"):
        problems.append("the catalog has actions but the capability 'execute' is not declared")
    missing = sorted(set(fixture.expect.entity_kinds) - manifest.kind_names)
    if missing:
        problems.append(f"entity kinds the fixture expects but the manifest does not declare: {missing}")
    if not manifest.entity_kinds:
        problems.append("the manifest declares no entity kind")
    return Finding("manifest", not problems, "; ".join(problems))


def check_context(request: Callable[..., Any]) -> Finding:
    raw = request("adapter.get_context", {})
    size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    Context.model_validate(raw)
    problems = [f"the context is {size} bytes, the limit is {MAX_CONTEXT_BYTES}"] if size > MAX_CONTEXT_BYTES else []
    return Finding("context", not problems, "; ".join(problems))


def check_min_entities(fixture: Fixture, obs: Observation) -> Finding:
    ok = len(obs.entities) >= fixture.expect.min_entities
    return Finding(
        "min_entities", ok, "" if ok else f"{len(obs.entities)} entities, wanted {fixture.expect.min_entities}"
    )


def check_catalog(fixture: Fixture, specs: list[ActionSpec]) -> Finding:
    got = {s.id for s in specs}
    want = set(fixture.expect.actions)
    problems: list[str] = []
    if got != want:
        problems.append(f"missing {sorted(want - got)}, extra {sorted(got - want)}")
    if len(got) != len(specs):
        problems.append("duplicate action ids")
    for s in specs:
        if CODE_RUNNING_ACTION.search(s.id):
            problems.append(f"'{s.id}' looks like an action that runs code (forbidden)")
        if (s.risk == "reversible") != s.reversible:
            problems.append(f"'{s.id}': risk '{s.risk}' and reversible={s.reversible} disagree")
        if s.params_schema.get("type") != "object":
            problems.append(f"'{s.id}': params_schema must describe an object")
    return Finding("action_catalog", not problems, "; ".join(problems))


def check_safe_call_risks(specs: list[ActionSpec], calls: list[dict[str, Any]]) -> list[str]:
    """The kit only executes what is safe to execute: nothing irreversible, ever."""
    risk = {s.id: s.risk for s in specs}
    return [
        f"safe call '{c['action_id']}' has risk '{risk[c['action_id']]}' (the kit never runs it)"
        for c in calls
        if risk.get(c["action_id"]) == "irreversible"
    ]


def check_dry_runs(request: Callable[..., Any], manifest: Manifest, calls: list[dict[str, Any]]) -> Finding:
    problems: list[str] = []
    for n, call in enumerate(calls):
        before = state_digest(request, manifest)
        try:
            raw = request(
                "adapter.execute",
                {"call": {"action_id": call["action_id"], "params": call["params"], "dry_run": True}},
            )
        except WyspError as exc:
            problems.append(f"dry run {n} {call['action_id']}: error {exc.code} {exc.message}")
            continue
        result = ActionResult.model_validate(raw)
        if result.undo_token:
            problems.append(f"dry run {n} {call['action_id']}: returned an undo token")
        if result.changed:
            problems.append(f"dry run {n} {call['action_id']}: reported changes {result.changed}")
        if state_digest(request, manifest) != before:
            problems.append(f"dry run {n} {call['action_id']}: the state digest changed")
    return Finding("dry_run", not problems, "; ".join(problems))


def check_invalid_calls(request: Callable[..., Any], manifest: Manifest, calls: list[dict[str, Any]]) -> Finding:
    problems: list[str] = []
    for n, call in enumerate(calls):
        before = state_digest(request, manifest)
        try:
            request("adapter.execute", {"call": {"action_id": call["action_id"], "params": call.get("params", {})}})
            problems.append(f"invalid call {n} {call['action_id']}: no error")
        except WyspError as exc:
            if exc.code != call["expect_error"]:
                problems.append(f"invalid call {n} {call['action_id']}: got {exc.code}, wanted {call['expect_error']}")
        if state_digest(request, manifest) != before:
            problems.append(f"invalid call {n} {call['action_id']}: the state digest changed")
    return Finding("invalid_calls", not problems, "; ".join(problems))


def check_state_versions(harness: Harness, series: dict[str, list[int]], pairs: list[tuple[int, int]]) -> Finding:
    """CON-P8. `series`: versions per source in the order seen; `pairs`: (result version, next observation version)."""
    problems: list[str] = []
    for source, versions in series.items():
        for earlier, later in zip(versions, versions[1:], strict=False):
            if later < earlier:
                problems.append(f"{source}: state_version went from {earlier} back to {later}")
                break
    for result_version, observed in pairs:
        if observed < result_version:
            problems.append(
                f"an observation reports state_version {observed}, behind the {result_version} just returned by execute"
            )
            break
    return Finding("state_version", not problems, "; ".join(problems))


def check_events(events: list[Event], wysp_phase: tuple[float, float] | None) -> Finding:
    """Event payloads validate; every state or user-action event caused by the kit's own calls is not tagged `user`."""
    problems: list[str] = []
    for ev in events:
        model = EVENT_MODELS.get(ev.method)
        if model is None:
            problems.append(f"unknown notification {ev.method}")
            continue
        try:
            data = model.model_validate(ev.params)
        except ValidationError as exc:
            problems.append(f"{ev.method}: invalid payload ({exc.errors()[0]['msg']})")
            continue
        origin = getattr(data, "origin", None)
        if wysp_phase and wysp_phase[0] <= ev.t <= wysp_phase[1] and origin == "user":
            problems.append(f"{ev.method} caused by a Wysp action is tagged origin 'user' (CON-P9)")
    return Finding("events", not problems, "; ".join(dict.fromkeys(problems)))


def check_highlight(request: Callable[..., Any], manifest: Manifest, obs: Observation) -> Finding:
    if not manifest.has("highlight"):
        return Finding("highlight", True, "capability not declared", skipped=True)
    ref = (obs.focus or [e.ref for e in obs.entities])[0]
    problems: list[str] = []
    result = request("adapter.highlight", {"ref": ref, "style": "pulse", "duration_ms": 300})
    if not isinstance(result, dict):
        problems.append("highlight did not return an object")
    if split_version(manifest.contract_version)[:2] >= (1, 1):
        request("adapter.highlight", {"ref": ref, "style": "outline", "duration_ms": 0})
        cleared = request("adapter.clear_highlight", {})
        if not (isinstance(cleared, dict) and cleared.get("cleared") is True):
            problems.append("clear_highlight did not report cleared=true after a persistent highlight")
    return Finding("highlight", not problems, "; ".join(problems))


# ------------------------------------------------------------------------------------------- the run


def run_online(fixture: Fixture, options: Options) -> Report:
    """Start the harness and the tutor, run every check, close everything. Never raises for an adapter fault."""
    import secrets

    report = Report(fixture.tutor)
    token = options.token or secrets.token_urlsafe(24)
    workdir = launchers.temp_workdir()
    harness = Harness(token, port=options.port)
    launched: launchers.Launched | None = None
    try:
        harness.start()
        if options.faults:
            fixture = fixture.model_copy(
                update={"launch": fixture.launch.model_copy(update={"faults": options.faults})}
            )
        try:
            launched = launchers.launch(fixture, harness.url, token, workdir, options.say)
        except (OSError, ValueError, ImportError, AttributeError) as exc:
            report.add(Finding("connect", False, f"cannot launch the adapter: {type(exc).__name__}: {exc}"))
            return report
        harness.allowed_origins |= launched.extra_origins
        timeout = options.timeout_s or fixture.launch.connect_timeout_s
        why = harness.wait_connected(timeout, launched.alive)
        report.add(Finding("connect", why is None, why or ""))
        if why is None:
            _checks(fixture, harness, launched, report)
    finally:
        if launched is not None:
            launched.stop()
        harness.stop()
        report.recording = harness.recording
        report.manifest = harness.manifest.model_dump(mode="json") if harness.manifest else None
        launchers.cleanup(workdir)
    return report


def _checks(fixture: Fixture, harness: Harness, launched: launchers.Launched, report: Report) -> None:
    request = harness.request
    manifest = harness.manifest
    assert manifest is not None
    safe = _calls(fixture.safe_calls, launched.substitutions)
    dry = _calls(fixture.dry_run_calls, launched.substitutions)
    invalid = _calls(fixture.invalid_calls, launched.substitutions)

    specs: list[ActionSpec] = []

    def load_specs() -> Finding:
        specs.extend(ActionSpec.model_validate(a) for a in request("adapter.get_actions", {}))
        return Finding("get_actions", True)

    # the content script / host may need a moment to read the application
    deadline = time.monotonic() + 20
    obs: Observation | None = None
    while time.monotonic() < deadline:
        try:
            obs = observe(request)[0]
        except WyspError:
            obs = None
        if obs is not None and len(obs.entities) >= fixture.expect.min_entities:
            break
        time.sleep(0.2)

    _timed(report, fixture, "get_actions", load_specs)
    _timed(report, fixture, "manifest", lambda: check_manifest(fixture, manifest, specs))
    _timed(report, fixture, "context", lambda: check_context(request))
    _timed(report, fixture, "observe_integrity", lambda: check_observe_integrity(request, manifest))
    _timed(report, fixture, "ref_stability", lambda: check_ref_stability(request, manifest))
    _timed(report, fixture, "min_entities", lambda: check_min_entities(fixture, observe(request)[0]))
    _timed(report, fixture, "action_catalog", lambda: check_catalog(fixture, specs))

    series: dict[str, list[int]] = {"observations": [], "results": []}
    pairs: list[tuple[int, int]] = []

    def traced_request(method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        """The checks' view of the adapter, plus a trace of state versions for CON-P8."""
        result = request(method, params, timeout)
        if method == "adapter.observe" and isinstance(result, dict) and isinstance(result.get("state_version"), int):
            series["observations"].append(result["state_version"])
            if pairs and pairs[-1][1] < 0:
                pairs[-1] = (pairs[-1][0], result["state_version"])
        if method in ("adapter.execute", "adapter.undo") and isinstance(result, dict):
            version = result.get("state_version")
            dry_run = bool((params or {}).get("call", {}).get("dry_run"))
            if isinstance(version, int) and not dry_run:
                series["results"].append(version)
                pairs.append((version, -1))
        return result

    risk_problems = check_safe_call_risks(specs, safe)
    phase_start = time.monotonic()
    if risk_problems:
        report.add(Finding("postconditions", False, "; ".join(risk_problems)))
        report.add(Finding("undo_round_trip", False, "not run: the safe calls include an irreversible action"))
    else:
        _timed(
            report,
            fixture,
            "postconditions",
            lambda: check_safe_calls(traced_request, manifest, safe),
            also=("undo_round_trip",),
        )
    phase_end = time.monotonic()
    time.sleep(SETTLE_S)
    _timed(report, fixture, "dry_run", lambda: check_dry_runs(request, manifest, dry))
    _timed(report, fixture, "invalid_calls", lambda: check_invalid_calls(request, manifest, invalid))
    pairs[:] = [p for p in pairs if p[1] >= 0]
    _timed(report, fixture, "state_version", lambda: check_state_versions(harness, series, pairs))
    _timed(report, fixture, "events", lambda: check_events(harness.events, (phase_start, phase_end + SETTLE_S)))
    _timed(report, fixture, "highlight", lambda: check_highlight(request, manifest, observe(request)[0]))
    over = harness.over_budget()
    report.add(Finding("latency", not over, "; ".join(over[:5])))


def write_junit(report: Report, path: Path) -> None:
    from xml.etree import ElementTree as ET

    failures = sum(1 for f in report.findings if not f.ok and not f.skipped)
    skipped = sum(1 for f in report.findings if f.skipped)
    suite = ET.Element(
        "testsuite",
        name=f"wysp-contract.{report.tutor}",
        tests=str(len(report.findings)),
        failures=str(failures),
        skipped=str(skipped),
        time=f"{sum(f.seconds for f in report.findings):.3f}",
    )
    for f in report.findings:
        case = ET.SubElement(
            suite, "testcase", classname=f"wysp-contract.{report.tutor}", name=f.check, time=f"{f.seconds:.3f}"
        )
        if f.skipped:
            ET.SubElement(case, "skipped", message=f.detail)
        elif not f.ok:
            ET.SubElement(case, "failure", message=f.detail[:500]).text = f.detail
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def write_recording(report: Report, path: Path) -> None:
    doc = {
        "tutor": report.tutor,
        "contract_version": CONTRACT_VERSION,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "manifest": report.manifest,
        "findings": [{"check": f.check, "ok": f.ok, "skipped": f.skipped, "detail": f.detail} for f in report.findings],
        "messages": report.recording,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def revalidate_recording(path: Path) -> list[str]:
    """Offline: check a recording's payloads against the current contract models."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if doc.get("manifest") is not None:
        try:
            Manifest.model_validate(doc["manifest"])
        except ValidationError as exc:
            problems.append(f"manifest: {exc.errors()[0]['msg']}")
    pending: dict[Any, str] = {}
    for entry in doc.get("messages", []):
        msg = entry["message"]
        if entry["dir"] == "to_adapter" and msg.get("id") is not None and "method" in msg:
            pending[msg["id"]] = msg["method"]
            continue
        try:
            if entry["dir"] == "from_adapter" and msg.get("method") in EVENT_MODELS:
                EVENT_MODELS[msg["method"]].model_validate(msg.get("params") or {})
            elif entry["dir"] == "from_adapter" and msg.get("id") in pending and "result" in msg:
                method = pending.pop(msg["id"])
                result = msg["result"]
                if method == "adapter.observe":
                    Observation.model_validate(result)
                elif method == "adapter.get_actions":
                    [ActionSpec.model_validate(a) for a in result]
                elif method == "adapter.get_context":
                    Context.model_validate(result)
                elif method in ("adapter.execute", "adapter.undo"):
                    ActionResult.model_validate(result)
        except ValidationError as exc:
            problems.append(f"t={entry['t']}: {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}")
    return problems
