"""Deterministic LLM for tests and offline demos: replays a scenario file.

Scenario YAML:
  steps:
    - when: "regex on the last user message"     # optional; first matching unused step wins
      say: "Optional text"
      calls:
        - {name: show_entities, arguments: {refs: ["x://a"], layout: stack}}
    - after_tool: show_entities                  # continues a turn once that tool result is in
      calls: [...]
Matching: a step with `when` fires on a new user message; a step with `after_tool` fires on the next
LLM round when the latest message is a result of that tool. Steps are consumed once.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import yaml

from .base import CancelToken, LLMResult, ToolCall, ToolSpec


class ScriptedLLM:
    name = "scripted"

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self.steps = [dict(s) for s in steps]
        self._used: set[int] = set()

    @classmethod
    def from_file(cls, path: str | Path) -> ScriptedLLM:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(data.get("steps", []))

    async def complete(self, messages: list[dict[str, Any]], tools: list[ToolSpec], cancel: CancelToken) -> LLMResult:
        last = messages[-1] if messages else {}
        for i, step in enumerate(self.steps):
            if i in self._used:
                continue
            if last.get("role") == "user" and "when" in step:
                if re.search(step["when"], str(last.get("content", "")), re.IGNORECASE):
                    self._used.add(i)
                    return self._result(step)
            elif last.get("role") == "tool" and step.get("after_tool") == last.get("name"):
                self._used.add(i)
                return self._result(step)
        if last.get("role") == "user":
            return LLMResult(text="I do not have a scripted answer for that.")
        return LLMResult()

    @staticmethod
    def _result(step: dict[str, Any]) -> LLMResult:
        calls = [
            ToolCall(id=uuid.uuid4().hex[:8], name=c["name"], arguments=dict(c.get("arguments", {})))
            for c in step.get("calls", [])
        ]
        return LLMResult(text=step.get("say", ""), tool_calls=calls)
