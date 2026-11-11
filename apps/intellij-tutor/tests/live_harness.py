"""Live contract check of the IntelliJ adapter: a minimal Core-side server that runs the contract fixture.

    uv run --no-sync python apps/intellij-tutor/tests/live_harness.py --port 8799 --token-file <file>

Start it, then start the sandbox IDE (gradlew runIde) with the plugin pointed at ws://127.0.0.1:<port>/ws/adapter.
Every reply is validated with the Core's own contract models (manifest, observation integrity, action specs,
results, context size); safe calls are executed, their postconditions evaluated on a fresh full observation,
then undone; invalid calls must return the expected error codes and leave the state digest unchanged.
Writes a JSON report and exits 0 when every check passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from websockets.asyncio.server import ServerConnection, serve
from wysp_core.contract.actions import ActionResult, ActionSpec
from wysp_core.contract.digest import digest
from wysp_core.contract.manifest import Manifest
from wysp_core.contract.observation import MAX_CONTEXT_BYTES, Context, Observation, check_observation
from wysp_core.contract.predicates import evaluate, substitute

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "apps" / "intellij-tutor" / "contract.fixture.yaml"


class Rpc:
    def __init__(self, ws: ServerConnection) -> None:
        self.ws = ws
        self.pending: dict[str, asyncio.Future] = {}
        self.notifications: list[dict[str, Any]] = []
        self.n = 0

    async def reader(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            if "method" in msg:
                self.notifications.append({"t": time.time(), **msg})
                continue
            fut = self.pending.pop(str(msg.get("id")), None)
            if fut and not fut.done():
                fut.set_result(msg)

    async def call(self, method: str, params: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        self.n += 1
        rid = f"h-{self.n}"
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        started = time.perf_counter()
        await self.ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
        msg = await asyncio.wait_for(fut, timeout)
        msg["_ms"] = round((time.perf_counter() - started) * 1000)
        return msg


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: Any = None) -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + ("" if ok or detail is None else f"  -> {detail}"), flush=True)
        return ok

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.checks)


async def run_checks(rpc: Rpc, manifest: Manifest, fixture: dict[str, Any], report: Report) -> None:
    kinds = manifest.kind_names
    expect = fixture["expect"]
    report.check("manifest kinds", set(expect["entity_kinds"]) <= kinds, sorted(kinds))

    msg = await rpc.call("adapter.get_actions", {})
    specs = [ActionSpec.model_validate(s) for s in msg["result"]]
    ids = [s.id for s in specs]
    report.check("get_actions ids", ids == expect["actions"], ids)
    report.check("get_actions consistency", not any(s.validate_consistency() for s in specs))
    by_id = {s.id: s for s in specs}

    async def observe(level: str = "full") -> Observation:
        m = await rpc.call("adapter.observe", {"scope": {"level": level}})
        return Observation.model_validate(m["result"])

    # Wait until the IDE is ready (indexing and the build-tool sync answer BUSY), then open a file to look at.
    deadline = time.time() + 300
    while time.time() < deadline:
        m = await rpc.call("adapter.get_context", {})
        if "result" in m and m["result"].get("mode") != "indexing":
            break
        await asyncio.sleep(2)
    first = fixture["safe_calls"][0]
    while time.time() < deadline:
        m = await rpc.call("adapter.execute", {"call": {**first, "request_id": "setup", "dry_run": False}})
        if "result" in m:
            break
        report.check("busy at startup is reported, never silent", m["error"]["code"] == -32017, m["error"])
        await asyncio.sleep(2)
    await asyncio.sleep(6)  # let the IDE highlight the file (problems come from its analysis)

    for level in ("summary", "focus", "full"):
        m = await rpc.call("adapter.observe", {"scope": {"level": level}})
        obs = Observation.model_validate(m["result"])
        problems = check_observation(obs, kinds)
        size = len(json.dumps(m["result"]))
        report.check(f"observe {level}: integrity", not problems, problems[:5])
        report.check(f"observe {level}: budget", m["_ms"] < 1000 and size <= 256 * 1024, {"ms": m["_ms"], "bytes": size})
    obs = await observe("full")
    for _ in range(30):  # problems come from the IDE's own analysis, which runs after indexing and sync
        if any(e.kind == "problem" for e in obs.entities):
            break
        await asyncio.sleep(1)
        obs = await observe("full")
    report.check("observe: enough entities", len(obs.entities) >= expect["min_entities"], len(obs.entities))
    report.check("observe: kinds seen", {e.kind for e in obs.entities} >= {"project", "module", "file", "symbol", "problem"}, sorted({e.kind for e in obs.entities}))

    m = await rpc.call("adapter.get_context", {})
    ctx = Context.model_validate(m["result"])
    size = len(json.dumps(m["result"], ensure_ascii=False).encode("utf-8"))
    report.check("get_context: size and budget", size <= MAX_CONTEXT_BYTES and m["_ms"] < 1000, {"bytes": size, "ms": m["_ms"], "summary": ctx.summary})

    for call in fixture.get("safe_calls", []):
        name = f"safe {call['action_id']} {json.dumps(call['params'])}"
        before = await observe()
        m = await rpc.call("adapter.execute", {"call": {**call, "request_id": f"r{rpc.n}", "dry_run": False}})
        if "error" in m:
            report.check(name, False, m["error"])
            continue
        res = ActionResult.model_validate(m["result"])
        spec = by_id[call["action_id"]]
        after = await observe()
        outcomes = [evaluate(substitute(p, call["params"]), after) for p in spec.postconditions]
        report.check(name + ": postconditions", all(o.ok for o in outcomes), [o.model_dump() for o in outcomes if not o.ok])
        if spec.reversible:
            report.check(name + ": undo token", bool(res.undo_token), res.model_dump())
            if res.undo_token:
                u = await rpc.call("adapter.undo", {"token": res.undo_token})
                ActionResult.model_validate(u.get("result") or {"status": "failed", "state_version": 0})
                restored = await observe()
                same = digest(restored, manifest.volatile_props) == digest(before, manifest.volatile_props)
                report.check(name + ": undo restores the digest", "result" in u and same, u.get("error"))
                again = await rpc.call("adapter.undo", {"token": res.undo_token})
                report.check(name + ": token is single-use", again.get("error", {}).get("code") == -32015, again.get("error"))

    for call in fixture.get("dry_run_calls", []):
        name = f"dry-run {call['action_id']}"
        before = await observe()
        m = await rpc.call("adapter.execute", {"call": {**call, "request_id": f"r{rpc.n}", "dry_run": True}})
        res = ActionResult.model_validate(m.get("result") or {"status": "failed", "state_version": 0})
        after = await observe()
        same = digest(after, manifest.volatile_props) == digest(before, manifest.volatile_props)
        report.check(name, "result" in m and res.preview is not None and not res.undo_token and same, m.get("error") or res.preview)

    for call in fixture.get("invalid_calls", []):
        name = f"invalid {call['action_id']} {json.dumps(call['params'])}"
        before = await observe()
        params = {k: v for k, v in call.items() if k != "expect_error"}
        m = await rpc.call("adapter.execute", {"call": {**params, "request_id": f"r{rpc.n}", "dry_run": False}})
        code = (m.get("error") or {}).get("code")
        after = await observe()
        same = digest(after, manifest.volatile_props) == digest(before, manifest.volatile_props)
        report.check(name, code == call["expect_error"] and same, {"code": code, "message": (m.get("error") or {}).get("message"), "unchanged": same})

    # Highlights: code, tool window, a visible label, and a label that is not there.
    for ref in fixture.get("highlights", []):
        m = await rpc.call("adapter.highlight", {"ref": ref, "style": "pulse", "duration_ms": 1500})
        report.check(f"highlight {ref}", "result" in m and m["_ms"] < 1500, m.get("error") or {"ms": m["_ms"], **m.get("result", {})})
        await asyncio.sleep(0.4)
    m = await rpc.call("adapter.highlight", {"ref": "intellij://ui/label/No Such Button Anywhere", "duration_ms": 1000})
    err = m.get("error") or {}
    report.check("highlight missing label lists visible labels", err.get("code") == -32012 and bool((err.get("data") or {}).get("visible")), err.get("message", "")[:300])

    await asyncio.sleep(1.0)
    kinds_seen = {}
    for n in rpc.notifications:
        kinds_seen[n["method"]] = kinds_seen.get(n["method"], 0) + 1
    report.check("heartbeat or events received", bool(kinds_seen), kinds_seen)
    changes = [n["params"] for n in rpc.notifications if n["method"] == "event.state_changed"]
    noise = [c for c in changes if any("/." in ref or "/build/" in ref for ref in c["changed"])]
    report.check("IDE settings and build output are not reported", not noise, noise[:3])
    renamed = [c for c in changes if any(ref.endswith("Library.java") for ref in c["changed"])]
    report.check("state changes from Wysp actions are tagged wysp", bool(renamed) and all(c["origin"] == "wysp" for c in renamed), renamed[-3:])


async def main_async(args: argparse.Namespace) -> int:
    fixture = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    fixture.setdefault("highlights", [
        "intellij://file/src/main/java/dev/wysp/sample/Library.java#Library.calc",
        "intellij://file/src/main/java/dev/wysp/sample/Main.java",
        "intellij://ui/toolwindow/Project",
        "intellij://ui/label/Project",
    ])
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    report = Report()
    done = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        hello = json.loads(await ws.recv())
        if hello.get("method") != "wysp.hello" or hello.get("params", {}).get("token") != token:
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": hello.get("id"), "error": {"code": -32019, "message": "bad pairing token"}}))
            report.check("hello token", False)
            return
        manifest = Manifest.model_validate(hello["params"]["manifest"])
        report.check("hello manifest", manifest.adapter_id == "intellij-tutor" and manifest.ref_scheme == "intellij", manifest.app.model_dump())
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": hello["id"], "result": {
            "session_id": "harness", "contract_version": "1.0.0", "core_version": "harness", "heartbeat_interval_s": 20}}))
        rpc = Rpc(ws)
        reader = asyncio.create_task(rpc.reader())
        try:
            await asyncio.sleep(args.settle)
            await run_checks(rpc, manifest, fixture, report)
        except Exception as exc:  # noqa: BLE001 - report and stop
            report.check("harness run", False, f"{type(exc).__name__}: {exc}")
        finally:
            reader.cancel()
            done.set()

    async with serve(handler, "127.0.0.1", args.port, process_request=None):
        print(f"harness listening on ws://127.0.0.1:{args.port}/ws/adapter", flush=True)
        try:
            await asyncio.wait_for(done.wait(), args.timeout)
        except TimeoutError:
            report.check("adapter connected", False, f"no adapter within {args.timeout} s")
    Path(args.report).write_text(json.dumps(report.checks, indent=2, ensure_ascii=False), encoding="utf-8")
    passed = sum(c["ok"] for c in report.checks)
    print(f"{passed}/{len(report.checks)} checks passed; report: {args.report}")
    return 0 if report.ok else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--settle", type=float, default=3.0, help="seconds to wait after hello (indexing, editors)")
    ap.add_argument("--report", default=str(REPO / ".tmp-home" / "intellij-harness.json"))
    sys.exit(asyncio.run(main_async(ap.parse_args())))


if __name__ == "__main__":
    main()
