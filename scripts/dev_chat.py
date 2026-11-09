"""Terminal Panel for development: talk to a running Wysp Core without the browser Panel.

    uv run python scripts/dev_chat.py                       # interactive
    uv run python scripts/dev_chat.py -m "Explain the pumpkin's modifiers" --auto-approve reversible

Shows narration, board changes, permission requests (asks y/n) and evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import websockets

sys.stdout.reconfigure(encoding="utf-8")


def board_line(board: dict) -> str:
    nodes = ", ".join(f"{n['label']}[{n['provenance'][0]}]" for n in board["nodes"])
    return f"board v{board['version']} ({board['layout']}): {nodes or '(empty)'}"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws/ui")
    parser.add_argument("-m", "--message", action="append", help="send this message (repeatable) then exit when idle")
    parser.add_argument("--auto-approve", choices=["none", "reversible", "all"], default="none")
    parser.add_argument("--timeout", type=float, default=90.0, help="seconds to wait for each turn (scripted mode)")
    args = parser.parse_args()

    board: dict = {"version": 0, "layout": "graph", "nodes": [], "edges": [], "steps": []}
    idle = asyncio.Event()
    segments: dict[str, dict] = {}

    async with websockets.connect(args.url) as ws:

        async def send(**msg) -> None:
            await ws.send(json.dumps(msg))

        async def reader() -> None:
            async for raw in ws:
                m = json.loads(raw)
                t = m["type"]
                if t == "narration.segment":
                    seg = m["segment"]
                    segments[seg["id"]] = seg
                    marker = f" ({seg['marker']})" if seg.get("marker") else ""
                    print(f"  🗣  {seg['text']}{marker}")
                    await send(type="narration.progress", segment_id=seg["id"], played=True)
                elif t == "board.snapshot":
                    board.update(m["board"])
                    print("  🧩", board_line(board))
                elif t == "board.patch":
                    print(
                        f"  🧩 patch v{m['patch']['version']}: " + ", ".join(op["op"] for op in m["patch"]["ops"])[:120]
                    )
                elif t == "activity":
                    print(f"  … {m['text']}")
                elif t == "status":
                    print(f"  [{m['state']}]")
                    if m["state"] == "idle":
                        idle.set()
                    else:
                        idle.clear()
                elif t == "permission.request":
                    print(f"  🔐 {m['title']} → {m['target']} [{m['risk']}] {m['rationale']}")
                    if m.get("preview"):
                        print(f"     preview: {m['preview']}")
                    approve = args.auto_approve == "all" or (
                        args.auto_approve == "reversible" and m["risk"] != "irreversible"
                    )
                    if args.auto_approve == "none":
                        approve = (await asyncio.to_thread(input, "     approve? [y/N] ")).strip().lower() == "y"
                    print("     ->", "approve" if approve else "deny")
                    await send(
                        type="permission.respond",
                        request_id=m["request_id"],
                        decision="approve" if approve else "deny",
                        via="click",
                    )
                elif t == "evidence.added":
                    ok = [o["ok"] for o in m["evidence"]["outcomes"]]
                    print(f"  ✅ evidence ({m['evidence']['type']}): {m['title']} outcomes={ok}")
                elif t == "clarification":
                    print(f"  ❓ {m['question']} {m['options']}")
                elif t == "error":
                    print(f"  ⚠ {m['code']}: {m['message']}")
                elif t in ("session.state", "adapters.list"):
                    if t == "session.state":
                        print(f"  session: adapter={m['active_adapter']} llm={m['llm']} profile={m['profile']}")

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.5)
        if args.message:
            for text in args.message:
                print(f"\n> {text}")
                idle.clear()
                await send(type="user.message", text=text)
                await asyncio.sleep(0.5)
                try:
                    await asyncio.wait_for(idle.wait(), args.timeout)
                except TimeoutError:
                    print("  (timeout waiting for the turn to finish)")
                await asyncio.sleep(0.5)
            task.cancel()
            return 0
        print("Type a message, /undo, /interrupt, /continue or /quit.")
        while True:
            line = await asyncio.to_thread(input, "> ")
            if line.strip() in ("/quit", "/q"):
                break
            if line.strip() == "/undo":
                await send(type="undo.last")
            elif line.strip() == "/interrupt":
                await send(type="user.interrupt")
            elif line.strip() == "/continue":
                await send(type="user.continue")
            elif line.strip():
                await send(type="user.message", text=line.strip())
        task.cancel()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
