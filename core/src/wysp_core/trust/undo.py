"""Per-adapter stack of undo tokens for changes made by Wysp (latest first)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class UndoRecord:
    request_id: str
    action_id: str
    title: str
    token: str


class UndoStack:
    def __init__(self, limit: int = 50) -> None:
        self._stacks: dict[str, list[UndoRecord]] = defaultdict(list)
        self._limit = limit

    def push(self, adapter_id: str, record: UndoRecord) -> None:
        stack = self._stacks[adapter_id]
        stack.append(record)
        del stack[: max(0, len(stack) - self._limit)]

    def pop(self, adapter_id: str) -> UndoRecord | None:
        stack = self._stacks[adapter_id]
        return stack.pop() if stack else None

    def peek(self, adapter_id: str) -> UndoRecord | None:
        stack = self._stacks[adapter_id]
        return stack[-1] if stack else None

    def remove(self, adapter_id: str, token: str) -> None:
        self._stacks[adapter_id] = [r for r in self._stacks[adapter_id] if r.token != token]
