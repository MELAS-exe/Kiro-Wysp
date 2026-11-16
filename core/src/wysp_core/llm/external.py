"""Placeholder provider for external-agent mode.

With `wysp serve --llm external` the Core does not call any language model. An AI agent that the user
already runs (connected through the MCP endpoint, `/mcp`) does the thinking and calls the Wysp tools;
the Core keeps the board, narration, permission gate, verification and audit. The Session checks
`external` and queues the user's messages for the agent instead of starting a turn, so `complete` is
never expected to run.
"""

from __future__ import annotations

from typing import Any

from .base import CancelToken, LLMResult, ToolSpec


class ExternalLLM:
    name = "external"
    model = None
    external = True

    async def complete(self, messages: list[dict[str, Any]], tools: list[ToolSpec], cancel: CancelToken) -> LLMResult:
        return LLMResult()
