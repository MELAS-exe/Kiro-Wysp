"""LIVE probe: drives the real Core's tools (over its MCP endpoint) against a connected browser connector.

    WYSP_MCP_URL=http://127.0.0.1:8799/mcp uv run --no-sync python apps/web-tutor/extension/tests/live/mcp_probe.py --token-file <path>

Run live_check.mjs with --hold first so that the extension stays connected. The token is read from the file
and never printed. Not part of `uv run pytest`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def summarize(result: object) -> str:
    text = "".join(getattr(c, "text", "") for c in getattr(result, "content", []))
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(data, ensure_ascii=False)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcp-url", default=os.environ.get("WYSP_MCP_URL", "http://127.0.0.1:8765/mcp"))
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args()
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    client = httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    failures = 0
    async with streamable_http_client(args.mcp_url, http_client=client) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name: str, arguments: dict[str, object]) -> str:
                result = await session.call_tool(name, arguments)
                out = summarize(result)
                print(f"{name}({json.dumps(arguments)[:120]}) -> {'ERR ' if result.is_error else ''}{out[:300]}")
                return out

            observed = await call("observe", {"level": "full"})
            failures += '"ok": false' in observed or "region~filters" not in observed
            for name, arguments in [
                (
                    "propose_action",
                    {
                        "action_id": "scroll_into_view",
                        "params": {"target": "web://localhost:5180/region~orders/table~orders-table"},
                        "mode": "do",
                    },
                ),
                ("highlight", {"ref": "web://localhost:5180/region~filters/combobox~region"}),
                ("clear_highlight", {}),
                ("propose_action", {"action_id": "nope", "params": {}, "mode": "do"}),
                (
                    "propose_action",
                    {
                        "action_id": "select_option",
                        "params": {
                            "target": "web://localhost:5180/region~filters/combobox~region",
                            "option": "Atlantis",
                        },
                        "mode": "do",
                    },
                ),
            ]:
                out = await call(name, arguments)
                if name == "propose_action" and arguments["action_id"] == "scroll_into_view":
                    failures += '"ok": false' in out
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
