"""LLM provider interface. The Core only needs: messages + tool specs in, text + tool calls out."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """Provider failure (network, rate limit, bad response). The message is safe to show the user."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class CancelToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


class LLMProvider(Protocol):
    name: str

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[ToolSpec], cancel: CancelToken
    ) -> LLMResult: ...
