"""Probe a connected IntelliJ adapter: serve, wait for the plugin, run calls, print the replies.

    uv run --no-sync python apps/intellij-tutor/tests/probe.py --token-file .tmp-home/harness-token \
        "adapter.get_context {}" "adapter.highlight {\"ref\": \"intellij://ui/label/Commit\"}"

Each call is "<method> <json params>". Use "sleep <seconds>" between calls to wait.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from websockets.asyncio.server import ServerConnection, serve


async def main_async(args: argparse.Namespace) -> int:
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    done = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        hello = json.loads(await ws.recv())
        if hello.get("params", {}).get("token") != token:
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": hello.get("id"), "error": {"code": -32019, "message": "bad token"}}))
            return
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": hello["id"], "result": {
            "session_id": "probe", "contract_version": "1.0.0", "core_version": "probe", "heartbeat_interval_s": 20}}))
        pending: dict[str, asyncio.Future] = {}

        async def reader() -> None:
            async for raw in ws:
                msg = json.loads(raw)
                if "method" in msg:
                    if args.events:
                        print("EVENT", json.dumps(msg, ensure_ascii=False)[:400], flush=True)
                    continue
                fut = pending.pop(str(msg.get("id")), None)
                if fut:
                    fut.set_result(msg)

        task = asyncio.create_task(reader())
        await asyncio.sleep(args.settle)
        for i, line in enumerate(args.calls):
            if line.startswith("sleep "):
                await asyncio.sleep(float(line.split()[1]))
                continue
            method, _, raw = line.partition(" ")
            fut = asyncio.get_running_loop().create_future()
            pending[f"p{i}"] = fut
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": f"p{i}", "method": method, "params": json.loads(raw or "{}")}))
            reply = await asyncio.wait_for(fut, 15)
            print(f"== {method}", json.dumps(reply.get("result", reply.get("error")), indent=1, ensure_ascii=False)[: args.max], flush=True)
        task.cancel()
        done.set()

    async with serve(handler, "127.0.0.1", args.port):
        print(f"probe listening on {args.port}", flush=True)
        await asyncio.wait_for(done.wait(), args.timeout)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("calls", nargs="*")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--settle", type=float, default=1.0)
    ap.add_argument("--max", type=int, default=6000)
    ap.add_argument("--events", action="store_true")
    sys.exit(asyncio.run(main_async(ap.parse_args())))


if __name__ == "__main__":
    main()
