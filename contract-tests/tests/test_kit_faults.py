"""The Kit's own test [adapter-contract 10]: it must FAIL on a faulty adapter, and say which check caught it.

The reference run is the mock adapter through the online harness (a real WebSocket, a real launcher in process).
Each fault of `wysp_mock.faults` is injected alone. If the kit stays green on a fault, the test goes red: the kit
would be silent about a contract violation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from wysp_contract import online
from wysp_contract.checks import Finding
from wysp_contract.cli import main as kit
from wysp_contract.fixture import Fixture, load_fixture, validate_fixture
from wysp_contract.harness import Harness, Timing, redact
from wysp_mock.faults import FAULTS

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mock" / "contract.fixture.yaml"

# fault -> the checks that must fail (any of them)
CAUGHT_BY = {
    "wrong_origin": {"events"},  # CON-P9
    "undo_noop": {"undo_round_trip"},  # CON-P6
    "undeclared_kind": {"observe_integrity"},  # CON-P2
    "postcondition_lie": {"postconditions"},  # CON-P7
    "state_version_regression": {"state_version"},  # CON-P8
    "dirty_invalid": {"invalid_calls"},  # CON-P5
    "dry_run_mutates": {"dry_run"},
    "unstable_digest": {"ref_stability"},  # CON-P3
}


@pytest.fixture(autouse=True)
def short_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(online, "SETTLE_S", 0.3)


def run(faults: list[str] | None = None, fixture: Fixture | None = None) -> online.Report:
    return online.run_online(fixture or load_fixture(FIXTURE), online.Options(faults=faults or [], say=lambda _: None))


def failed(report: online.Report) -> set[str]:
    return {f.check for f in report.findings if not f.ok and not f.skipped}


def test_every_fault_is_listed_here() -> None:
    assert set(CAUGHT_BY) == FAULTS


def test_the_fixture_is_valid() -> None:
    assert validate_fixture(FIXTURE) == []


def test_the_reference_mock_passes_every_check() -> None:
    report = run()
    assert report.ok, [str(f) for f in report.findings if not f.ok]
    names = [f.check for f in report.findings]
    for expected in ("connect", "manifest", "observe_integrity", "ref_stability", "postconditions", "undo_round_trip",
                     "dry_run", "invalid_calls", "state_version", "events", "latency"):  # fmt: skip
        assert expected in names


def test_the_reference_mock_does_report_events_so_the_origin_check_is_not_vacuous() -> None:
    report = run()
    sent = [
        m
        for m in report.recording
        if m["dir"] == "from_adapter" and m["message"].get("method") == "event.state_changed"
    ]
    assert sent and all(m["message"]["params"]["origin"] == "wysp" for m in sent)


@pytest.mark.parametrize("fault", sorted(CAUGHT_BY))
def test_prop_con_the_kit_fails_on_fault(fault: str) -> None:
    """CON-P2/P3/P5/P6/P7/P8/P9: a fault that no check reports is a hole in the kit."""
    report = run([fault])
    assert not report.ok, f"the kit is silent about the fault {fault!r}"
    assert failed(report) & CAUGHT_BY[fault], (
        f"{fault}: failed {sorted(failed(report))}, wanted one of {CAUGHT_BY[fault]}"
    )


def test_the_kit_stays_green_with_300_ms_of_latency() -> None:
    report = run(["latency_ms=300"])
    assert report.ok, [str(f) for f in report.findings if not f.ok]


def test_an_unknown_fault_is_rejected_before_anything_connects() -> None:
    report = run(
        ["no_such_fault"],
        load_fixture(FIXTURE).model_copy(
            update={"launch": load_fixture(FIXTURE).launch.model_copy(update={"connect_timeout_s": 2})}
        ),
    )
    assert not report.ok and "connect" in failed(report)


def test_a_fixture_skip_is_reported_but_never_failing() -> None:
    fixture = Fixture.model_validate(
        {**load_fixture(FIXTURE).model_dump(), "skip": [{"check": "highlight", "reason": "no viewport"}]}
    )
    report = run(None, fixture)
    skipped = [f for f in report.findings if f.skipped]
    assert [f.check for f in skipped] == ["highlight"] and report.ok


def test_irreversible_actions_are_never_run_as_safe_calls() -> None:
    fixture = load_fixture(FIXTURE)
    fixture = Fixture.model_validate(
        {**fixture.model_dump(), "safe_calls": [{"action_id": "archive_card", "params": {"card": "mock://card/c3"}}]}
    )
    report = run(None, fixture)
    assert "postconditions" in failed(report)
    real_calls = [
        m["message"]["params"]["call"]
        for m in report.recording
        if m["dir"] == "to_adapter" and m["message"].get("method") == "adapter.execute"
    ]
    assert not [c for c in real_calls if c["action_id"] == "archive_card" and not c.get("dry_run")]


def test_junit_and_recording_are_written_and_the_recording_has_no_token(tmp_path: Path) -> None:
    junit, recording = tmp_path / "out" / "kit.junit.xml", tmp_path / "rec" / "kit.json"
    assert kit(["--fixture", str(FIXTURE), "--junit", str(junit), "--recording", str(recording)]) == 0
    xml = junit.read_text(encoding="utf-8")
    assert 'failures="0"' in xml and 'name="undo_round_trip"' in xml
    doc = json.loads(recording.read_text(encoding="utf-8"))
    hello = next(m["message"] for m in doc["messages"] if m["message"].get("method") == "wysp.hello")
    assert hello["params"]["token"] == "***"
    assert doc["manifest"]["adapter_id"] == "mock-kanban"
    assert online.revalidate_recording(recording) == []


def test_junit_reports_a_failure_with_its_detail(tmp_path: Path) -> None:
    junit = tmp_path / "bad.junit.xml"
    assert kit(["--fixture", str(FIXTURE), "--fault", "undo_noop", "--junit", str(junit)]) == 1
    xml = junit.read_text(encoding="utf-8")
    assert "<failure" in xml and "digest after undo" in xml


def test_a_recording_that_no_longer_matches_the_contract_is_reported_offline(tmp_path: Path) -> None:
    recording = tmp_path / "rec.json"
    kit(["--fixture", str(FIXTURE), "--recording", str(recording)])
    doc = json.loads(recording.read_text(encoding="utf-8"))
    for m in doc["messages"]:
        result = m["message"].get("result")
        if isinstance(result, dict) and "entities" in result:
            result["entities"] = [{"bogus": 1}]
            break
    recording.write_text(json.dumps(doc), encoding="utf-8")
    assert online.revalidate_recording(recording)


def test_redact_hides_secret_keys_at_any_depth() -> None:
    out = redact({"params": {"token": "t", "nested": [{"api_key": "k", "ok": 1}]}})
    assert out == {"params": {"token": "***", "nested": [{"api_key": "***", "ok": 1}]}}


def test_latency_check_flags_a_request_over_its_budget() -> None:
    h = Harness("t")
    h.timings += [
        Timing("adapter.observe", 0.4, True),
        Timing("adapter.observe", 2.6, True),
        Timing("adapter.execute", 5.5, True),
    ]
    assert len(h.over_budget()) == 1 and "adapter.observe" in h.over_budget()[0]


def test_the_harness_refuses_a_wrong_token_and_a_disallowed_origin() -> None:
    import asyncio

    import websockets

    harness = Harness("right-token", allowed_origins={"chrome-extension://ok"})
    harness.start()
    try:

        async def attempt(token: str, origin: str | None) -> str:
            headers = {"Origin": origin} if origin else {}
            try:
                async with websockets.connect(harness.url, additional_headers=headers) as ws:
                    await ws.send(
                        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "wysp.hello", "params": {"token": token}})
                    )
                    return json.dumps(json.loads(await ws.recv()).get("error", {}).get("code"))
            except websockets.ConnectionClosed as exc:
                return f"closed {exc.rcvd.code if exc.rcvd else None}"
            except websockets.InvalidStatus as exc:
                return f"status {exc.response.status_code}"

        assert asyncio.run(attempt("wrong", None)) == "-32019"
        assert asyncio.run(attempt("right-token", "http://evil.example")).startswith(("closed 4403", "status"))
    finally:
        harness.stop()
    assert harness.manifest is None


def test_a_finding_prints_its_status() -> None:
    assert str(Finding("x", True, skipped=True, detail="why")) == "SKIP x: why"


def test_the_published_fixture_schema_is_up_to_date() -> None:
    """Regenerate with: uv run python -m wysp_contract.fixture"""
    published = json.loads((Path(online.__file__).parent / "fixture.schema.json").read_text(encoding="utf-8"))
    assert published == json.loads(json.dumps(Fixture.model_json_schema(), sort_keys=True))
