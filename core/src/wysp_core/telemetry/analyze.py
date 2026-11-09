"""Offline analysis of session logs: where does the time go, what fails, what did the user get?

    wysp logs list                       the log files, newest first
    wysp logs summary [--file F] [--json]   latency, errors, turns, guide outcomes (core + adapter logs merged)
    wysp logs timeline [--file F]        a chronological, human-readable trace

Reads the JSONL written by `Telemetry` (role "core") and by adapters (any other role).
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .recorder import percentile


def log_dir() -> Path:
    from ..store import wysp_home

    return wysp_home() / "logs"


def list_logs(directory: Path | None = None) -> list[Path]:
    d = directory or log_dir()
    return sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if d.exists() else []


def read(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _ts(rec: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(rec["ts"])


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 1),
        "p50": round(percentile(values, 50), 1),
        "p95": round(percentile(values, 95), 1),
        "max": round(max(values), 1),
    }


def related_logs(core_log: Path, directory: Path | None = None) -> list[Path]:
    """Adapter logs whose time range overlaps the core log."""
    core = read(core_log)
    if not core:
        return []
    start, end = _ts(core[0]), _ts(core[-1])
    found = []
    for p in list_logs(directory or core_log.parent):
        if p == core_log:
            continue
        recs = read(p)
        if recs and recs[0].get("role") != "core" and _ts(recs[0]) <= end and _ts(recs[-1]) >= start:
            found.append(p)
    return found


def summarize(core_log: Path, extra: list[Path] | None = None) -> dict[str, Any]:
    core = read(core_log)
    adapters: list[dict[str, Any]] = []
    for p in extra if extra is not None else related_logs(core_log):
        adapters += read(p)
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in core:
        by_kind[r["kind"]].append(r)
    ad_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in adapters:
        ad_kind[r["kind"]].append(r)

    def durations(recs: list[dict[str, Any]]) -> list[float]:
        return [r["duration_ms"] for r in recs if isinstance(r.get("duration_ms"), (int, float))]

    start = by_kind["session.start"][0] if by_kind["session.start"] else core[0]
    out: dict[str, Any] = {
        "file": str(core_log),
        "started": start.get("ts"),
        "wall_s": round((_ts(core[-1]) - _ts(core[0])).total_seconds(), 1) if core else 0,
        "log_level_at_start": start.get("level") or "?",
        "llm": {"provider": start.get("llm_provider"), "model": start.get("llm_model")},
        "records": len(core),
        "adapter_records": len(adapters),
    }

    # --- turns
    turns = by_kind["turn"]
    out["turns"] = {
        "n": len(turns),
        "outcomes": dict(Counter(t.get("outcome") for t in turns)),
        "total_ms": stats(durations(turns)),
        "llm_ms": stats([t["llm_ms"] for t in turns if "llm_ms" in t]),
        "tool_ms": stats([t["tool_ms"] for t in turns if "tool_ms" in t]),
        "first_segment_ms": stats([t["first_segment_ms"] for t in turns if t.get("first_segment_ms") is not None]),
        "rounds": stats([float(t["rounds"]) for t in turns if "rounds" in t]),
    }
    out["turn_list"] = [
        {
            "at": t.get("ts"),
            "user": None,
            "total_ms": t.get("duration_ms"),
            "llm_ms": t.get("llm_ms"),
            "tool_ms": t.get("tool_ms"),
            "first_segment_ms": t.get("first_segment_ms"),
            "rounds": t.get("rounds"),
            "segments": t.get("segments"),
            "outcome": t.get("outcome"),
        }
        for t in turns
    ]
    # attach the user text of each turn (the last user.message before the turn record's start)
    user_msgs = by_kind["user.message"]
    for item, t in zip(out["turn_list"], turns, strict=False):
        started_at = t["t_ms"] - (t.get("duration_ms") or 0)
        prior = [u for u in user_msgs if u["t_ms"] <= started_at + 50]
        item["user"] = prior[-1].get("text", f"({prior[-1].get('chars')} chars)") if prior else None

    # --- LLM
    reqs = by_kind["llm.request"]
    out["llm_requests"] = {
        "n": len(reqs),
        "latency_ms": stats(durations(reqs)),
        "failed": sum(1 for r in reqs if r.get("ok") is False),
        "attempts_total": sum(r.get("attempts", 1) for r in reqs),
        "timeouts": sum(r.get("timeouts", 0) for r in reqs),
        "rate_limited": sum(r.get("rate_limited", 0) for r in reqs),
        "rate_wait_s": round(sum(r.get("rate_wait_ms", 0) for r in reqs) / 1000, 1),
        "server_errors": sum(r.get("server_errors", 0) for r in reqs),
        "hedged": sum(1 for r in reqs if r.get("hedged")),
        "prompt_chars": stats([float(r["prompt_chars"]) for r in reqs if "prompt_chars" in r]),
        "tokens": _token_stats(reqs),
        "recovered_from_text": len(by_kind["llm.recovered_tool_call"]),
        "retries_by_turn": len(by_kind["llm.retry"]),
    }

    # --- tools & adapter calls
    tools: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in by_kind["tool.call"]:
        tools[r.get("tool", "?")].append(r)
    out["tools"] = {
        name: {**stats(durations(rs)), "errors": sum(1 for r in rs if r.get("ok") is False)}
        for name, rs in sorted(tools.items())
    }
    calls: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in by_kind["adapter.call"]:
        calls[r.get("method", "?")].append(r)
    out["adapter_calls"] = {
        m: {**stats(durations(rs)), "errors": sum(1 for r in rs if r.get("ok") is False)}
        for m, rs in sorted(calls.items())
    }

    # --- adapter-side performance
    out["adapter_side"] = {
        "request_queue_ms": stats([r["queue_ms"] for r in ad_kind["request"] if "queue_ms" in r]),
        "request_run_ms": stats([r["run_ms"] for r in ad_kind["request"] if "run_ms" in r]),
        "slow_ticks": len(ad_kind["slow_tick"]),
        "observe_ms": stats([r["duration_ms"] for r in ad_kind["observe"] if "duration_ms" in r]),
        "errors": [
            r.get("summary") or r.get("message") for r in ad_kind["log"] if r.get("level_name") in ("ERROR", "CRITICAL")
        ][:10],
    }

    # --- guides, permissions, narration
    out["guides"] = {
        "started": len(by_kind["guide.start"]),
        "verified": len(by_kind["guide.verified"]),
        "checks": len(by_kind["guide.check"]),
        "checks_ok": sum(1 for r in by_kind["guide.check"] if r.get("ok")),
    }
    perms = by_kind["permission"]
    out["permissions"] = {
        "n": len(perms),
        "approved": sum(1 for p in perms if p.get("approved")),
        "wait_ms": stats(durations(perms)),
        "by_policy": dict(Counter(p.get("policy") for p in perms)),
    }
    out["actions"] = {
        "executed": len(by_kind["action.execute"]),
        "verified_ok": sum(1 for r in by_kind["action.verify"] if r.get("ok")),
        "verify_failed": sum(1 for r in by_kind["action.verify"] if r.get("ok") is False),
        "verify_ms": stats(durations(by_kind["action.verify"])),
    }
    out["narration"] = {
        "segments": len(by_kind["narration.segment"]),
        "blocked_tool_markup": len(by_kind["narration.blocked"]),
        "interrupts": len(by_kind["interrupt"]),
    }
    out["adapter_events"] = dict(Counter(f"{r.get('name')}:{r.get('origin')}" for r in by_kind["adapter.event"]))
    out["warnings"] = [
        {"at": r.get("ts"), "logger": r.get("logger"), "summary": r.get("summary")}
        for r in by_kind["log"]
        if r.get("level_name") in ("WARNING", "ERROR", "CRITICAL")
    ][-15:]
    out["findings"] = findings(out)
    return out


def _token_stats(reqs: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = [r["usage"]["prompt_tokens"] for r in reqs if r.get("usage") and "prompt_tokens" in r["usage"]]
    comp = [r["usage"]["completion_tokens"] for r in reqs if r.get("usage") and "completion_tokens" in r["usage"]]
    return {
        "prompt": stats([float(x) for x in prompt]),
        "completion": stats([float(x) for x in comp]),
        "total": sum(prompt) + sum(comp),
    }


def findings(s: dict[str, Any]) -> list[str]:
    """Plain-language observations a developer can act on."""
    f: list[str] = []
    t, lr, a = s["turns"], s["llm_requests"], s["adapter_side"]
    if t["n"] and t["total_ms"].get("p50", 0) > 8000:
        f.append(f"Turns are slow: median {t['total_ms']['p50'] / 1000:.1f}s (p95 {t['total_ms']['p95'] / 1000:.1f}s).")
    if (
        t["n"]
        and t["llm_ms"].get("mean")
        and t["total_ms"].get("mean")
        and t["llm_ms"]["mean"] / t["total_ms"]["mean"] > 0.7
    ):
        f.append("Most of each turn is spent waiting for the LLM, not in the application or in Wysp.")
    if lr["rate_limited"]:
        f.append(
            f"The LLM provider rate-limited us {lr['rate_limited']} time(s), costing {lr['rate_wait_s']}s of waiting. Shrink prompts or switch model."
        )
    if lr["timeouts"]:
        f.append(f"{lr['timeouts']} LLM request(s) timed out; hedged retries were used {lr['hedged']} time(s).")
    if lr["recovered_from_text"]:
        f.append(f"The model wrote a tool call as plain text {lr['recovered_from_text']} time(s) (recovered).")
    if s["narration"]["blocked_tool_markup"]:
        f.append(f"{s['narration']['blocked_tool_markup']} tool-call-looking text(s) were blocked from being spoken.")
    if lr["prompt_chars"].get("p50", 0) > 14000:
        f.append(f"Prompts are large (median {int(lr['prompt_chars']['p50'])} chars): that costs latency and tokens.")
    g = s["guides"]
    if g["started"] and not g["verified"]:
        f.append(
            f"{g['started']} guided step(s) started but none was verified: check the adapter's state_changed events and the postconditions."
        )
    if a["request_queue_ms"].get("p95", 0) > 150:
        f.append(
            f"The application answers slowly to requests: p95 queue wait {a['request_queue_ms']['p95']}ms (is the pump timer starved?)."
        )
    if a["slow_ticks"]:
        f.append(f"{a['slow_ticks']} slow adapter tick(s): the main thread was blocked.")
    if s["actions"]["verify_failed"]:
        f.append(f"{s['actions']['verify_failed']} action(s) ran but failed verification.")
    if not f:
        f.append("No problem detected in this session.")
    return f


def render(s: dict[str, Any]) -> str:
    def row(label: str, d: dict[str, float]) -> str:
        if not d.get("n"):
            return f"  {label:<24} (none)"
        return f"  {label:<24} n={d['n']:<4} mean={d['mean']:<8} p50={d['p50']:<8} p95={d['p95']:<8} max={d['max']}"

    L = [
        f"Session log: {s['file']}",
        f"  started {s['started']}  wall time {s['wall_s']}s  LLM {s['llm']['provider']} / {s['llm']['model']}",
        "",
    ]
    t = s["turns"]
    L += [
        f"TURNS  n={t['n']}  outcomes={t['outcomes']}",
        row("total (ms)", t["total_ms"]),
        row("llm wait (ms)", t["llm_ms"]),
        row("tools (ms)", t["tool_ms"]),
        row("first segment (ms)", t["first_segment_ms"]),
        row("rounds", t["rounds"]),
        "",
    ]
    for i, tl in enumerate(s["turn_list"], 1):
        L.append(
            f"  #{i} {str(tl['user'])[:60]!r:<64} total={tl['total_ms']}ms llm={tl['llm_ms']}ms tools={tl['tool_ms']}ms first={tl['first_segment_ms']}ms rounds={tl['rounds']} -> {tl['outcome']}"
        )
    lr = s["llm_requests"]
    L += [
        "",
        f"LLM  requests={lr['n']} failed={lr['failed']} attempts={lr['attempts_total']} timeouts={lr['timeouts']} rate_limited={lr['rate_limited']} (waited {lr['rate_wait_s']}s) hedged={lr['hedged']}",
        row("latency (ms)", lr["latency_ms"]),
        row("prompt (chars)", lr["prompt_chars"]),
        row("prompt tokens", lr["tokens"]["prompt"]),
        row("completion tokens", lr["tokens"]["completion"]),
        f"  tokens total: {lr['tokens']['total']}   tool calls recovered from text: {lr['recovered_from_text']}",
    ]
    L += ["", "TOOLS"] + [
        row(k, v) + (f"  errors={v['errors']}" if v.get("errors") else "") for k, v in s["tools"].items()
    ]
    L += ["", "ADAPTER CALLS (Core -> app)"] + [
        row(k, v) + (f"  errors={v['errors']}" if v.get("errors") else "") for k, v in s["adapter_calls"].items()
    ]
    a = s["adapter_side"]
    L += [
        "",
        f"ADAPTER SIDE (records: {s['adapter_records']})",
        row("queue wait (ms)", a["request_queue_ms"]),
        row("handler run (ms)", a["request_run_ms"]),
        row("observe build (ms)", a["observe_ms"]),
        f"  slow ticks: {a['slow_ticks']}",
    ]
    g, p, ac, n = s["guides"], s["permissions"], s["actions"], s["narration"]
    L += [
        "",
        f"GUIDES started={g['started']} verified={g['verified']} checks={g['checks']} (ok {g['checks_ok']})",
        f"PERMISSIONS n={p['n']} approved={p['approved']} by_policy={p['by_policy']}",
        row("decision wait (ms)", p["wait_ms"]),
        f"ACTIONS executed={ac['executed']} verified_ok={ac['verified_ok']} verify_failed={ac['verify_failed']}",
        f"NARRATION segments={n['segments']} blocked_markup={n['blocked_tool_markup']} interrupts={n['interrupts']}",
        f"ADAPTER EVENTS {s['adapter_events']}",
    ]
    if s["warnings"]:
        L += ["", "WARNINGS / ERRORS (last 15)"] + [f"  {w['at']} {w['logger']}: {w['summary']}" for w in s["warnings"]]
    L += ["", "FINDINGS"] + [f"  - {x}" for x in s["findings"]]
    return "\n".join(L)


def timeline(core_log: Path, include_adapters: bool = True) -> str:
    recs = read(core_log)
    if include_adapters:
        for p in related_logs(core_log):
            recs += read(p)
    recs.sort(key=lambda r: r["ts"])
    skip = {"status", "board.patch", "narration.progress"}
    lines = []
    for r in recs:
        if r["kind"] in skip and r.get("role") == "core":
            continue
        detail = {
            k: v
            for k, v in r.items()
            if k not in ("ts", "t_ms", "role", "session", "kind", "seq", "usage") and v is not None
        }
        txt = json.dumps(detail, ensure_ascii=False)
        lines.append(f"{r['ts'][11:23]} {r['role'][:3]} {r['kind']:<22} {txt[:230]}")
    return "\n".join(lines)
