"""Measure round-trip latency of a free LLM endpoint with a tiny and a realistic request.

uv run python scripts/llm_latency.py [provider]      # default: whatever `from_env()` picks
"""

from __future__ import annotations

import asyncio
import sys
import time

from dotenv import load_dotenv
from wysp_core.app import find_repo_root
from wysp_core.llm import CancelToken, LLMError, ToolSpec, from_env
from wysp_core.orchestrator.tools import tool_specs


async def timed(provider, label: str, messages: list[dict], tools: list[ToolSpec]) -> None:
    t0 = time.monotonic()
    try:
        result = await provider.complete(messages, tools, CancelToken())
        dt = time.monotonic() - t0
        what = f"{len(result.tool_calls)} tool call(s)" if result.tool_calls else f"text: {result.text[:50]!r}"
        print(f"{label:34s} {dt:6.1f}s  {what}")
    except LLMError as exc:
        print(f"{label:34s} {time.monotonic() - t0:6.1f}s  ERROR {exc}")


async def main() -> None:
    load_dotenv(find_repo_root() / ".env")
    if len(sys.argv) > 1:
        import os

        os.environ["WYSP_LLM_PROVIDER"] = sys.argv[1]
    provider = from_env()
    print(f"provider={provider.name} model={provider.model}")
    caps = {"observe", "actions", "highlight", "context", "execute", "undo"}
    tools = tool_specs(caps)
    big_system = "You are a tutor. " + ("Context line about the scene. " * 150)
    await timed(provider, "tiny, no tools", [{"role": "user", "content": "Say hi in 3 words."}], [])
    await timed(provider, "tiny, 9 tools", [{"role": "user", "content": "Say hi in 3 words."}], tools)
    await timed(
        provider,
        "realistic prompt (~900 tokens) + tools",
        [{"role": "system", "content": big_system}, {"role": "user", "content": "Explain the pumpkin."}],
        tools,
    )


if __name__ == "__main__":
    asyncio.run(main())
