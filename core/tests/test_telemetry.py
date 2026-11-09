"""Telemetry: levels, content gating, redaction, spans, analysis, and tool-markup handling."""

from __future__ import annotations

import json
from pathlib import Path

from wysp_core.narration import looks_like_tool_markup
from wysp_core.orchestrator.tools import recover_tool_call
from wysp_core.telemetry import Telemetry, analyze


def _records(tm: Telemetry) -> list[dict]:
    assert tm.path is not None
    return [json.loads(line) for line in tm.path.read_text(encoding="utf-8").splitlines()]


def test_off_writes_nothing(tmp_path: Path) -> None:
    tm = Telemetry(level="off", directory=tmp_path)
    tm.emit("turn", duration_ms=5)
    assert tm.path is None
    assert list(tmp_path.iterdir()) == []


def test_basic_omits_content_full_keeps_it(tmp_path: Path) -> None:
    tm = Telemetry(level="basic", directory=tmp_path)
    tm.emit("user.message", full={"text": "hello"}, chars=5)
    assert "text" not in _records(tm)[-1]
    tm.set_level("full")
    tm.emit("user.message", full={"text": "hello"}, chars=5)
    assert _records(tm)[-1]["text"] == "hello"
    assert any(r["kind"] == "log.level" for r in _records(tm))


def test_secrets_are_redacted(tmp_path: Path) -> None:
    tm = Telemetry(level="full", directory=tmp_path)
    tm.emit("llm.request", full={"headers": {"Authorization": "Bearer gsk_abcdefghijklmnopqrstuvwxyz0123456789"}})
    assert "gsk_abcdefghijklmnop" not in tm.path.read_text(encoding="utf-8")  # type: ignore[union-attr]


def test_span_records_duration_and_errors(tmp_path: Path) -> None:
    tm = Telemetry(level="basic", directory=tmp_path)
    with tm.span("tool.call", tool="x"):
        pass
    try:
        with tm.span("tool.call", tool="y"):
            raise ValueError("boom")
    except ValueError:
        pass
    m = tm.metrics()["timings"]["tool.call"]
    assert m["n"] == 2 and m["errors"] == 1


def test_summary_and_findings_on_a_synthetic_session(tmp_path: Path) -> None:
    tm = Telemetry(level="full", directory=tmp_path)
    tm.emit("user.message", full={"text": "what is this?"}, chars=13)
    tm.emit("llm.request", duration_ms=900, ok=True, attempts=1, rate_limited=1, rate_wait_ms=2000)
    tm.emit("turn", duration_ms=1200, llm_ms=1000, tool_ms=50, rounds=2, outcome="done", first_segment_ms=800)
    tm.emit("guide.start", ref="a://b")
    tm.close()
    assert tm.path is not None
    summary = analyze.summarize(tm.path, extra=[])
    assert summary["turns"]["n"] == 1
    assert summary["llm_requests"]["rate_limited"] == 1
    assert any("none was verified" in f for f in summary["findings"])
    assert "TURNS" in analyze.render(summary)


def test_tool_call_wrapped_in_angle_brackets_is_recovered() -> None:
    text = '<narrate{ "segments": [ { "text": "Hi", "provenance": "inferred" } ] }>'
    recovered = recover_tool_call(text, {"narrate"})
    assert recovered is not None
    assert recovered.name == "narrate" and recovered.arguments["segments"][0]["text"] == "Hi"


def test_tool_markup_is_not_speakable() -> None:
    assert looks_like_tool_markup('<narrate{ "segments": [] }>')
    assert looks_like_tool_markup('<function=narrate>{"segments": []}</function>')
    assert not looks_like_tool_markup("The Candle has a Bevel modifier.")
