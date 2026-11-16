"""Adapter runtime: action registry, undo tokens, origin tagging and method routing."""

from __future__ import annotations

import itertools
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from . import schema
from .errors import ErrorCode, WyspError

log = logging.getLogger("wysp.adapter")


@dataclass
class ActionOutcome:
    """What an action function returns."""

    changed: list[str] = field(default_factory=list)
    undo: Callable[[], None] | None = None
    message: str | None = None
    preview: Any = None


ActionFn = Callable[[dict[str, Any], bool], ActionOutcome]  # (params, dry_run) -> outcome


class OriginTagger:
    """Marks state changes as caused by Wysp for a short window after an action runs."""

    def __init__(self, window_s: float = 0.6) -> None:
        self.window_s = window_s
        self._until = 0.0
        self._lock = threading.Lock()

    @contextmanager
    def wysp(self):
        try:
            yield
        finally:
            with self._lock:
                self._until = time.monotonic() + self.window_s

    def current(self) -> str:
        with self._lock:
            return "wysp" if time.monotonic() < self._until else "user"


class ActionRegistry:
    """Closed catalog of actions. Validates params, runs them, and keeps undo records."""

    def __init__(self, max_undo: int = 200) -> None:
        self._actions: dict[str, tuple[dict[str, Any], ActionFn]] = {}
        self._undo: OrderedDict[str, Callable[[], None]] = OrderedDict()
        self._max_undo = max_undo
        self._counter = itertools.count(1)

    def register(self, spec: dict[str, Any], fn: ActionFn) -> None:
        if spec["risk"] == "reversible" and not spec.get("reversible"):
            raise ValueError(f"{spec['id']}: risk 'reversible' requires reversible=true")
        if spec["id"] in self._actions:
            raise ValueError(f"duplicate action id {spec['id']}")
        self._actions[spec["id"]] = (spec, fn)

    def specs(self) -> list[dict[str, Any]]:
        return [spec for spec, _ in self._actions.values()]

    def has(self, action_id: str) -> bool:
        return action_id in self._actions

    def execute(
        self, call: dict[str, Any], state_version: Callable[[], int], bump: Callable[[], int]
    ) -> dict[str, Any]:
        action_id = call.get("action_id", "")
        entry = self._actions.get(action_id)
        if entry is None:
            raise WyspError(ErrorCode.ACTION_NOT_FOUND, f"unknown action '{action_id}'")
        spec, fn = entry
        params = call.get("params") or {}
        problems = schema.validate(params, spec["params_schema"])
        if problems:
            raise WyspError(ErrorCode.INVALID_PARAMS, "invalid parameters", {"problems": problems})
        dry_run = bool(call.get("dry_run"))
        try:
            outcome = fn(params, dry_run)
        except WyspError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("action %s failed", action_id)
            raise WyspError(ErrorCode.EXECUTION_FAILED, f"{type(exc).__name__}: {exc}") from exc
        if dry_run:
            return {"status": "ok", "state_version": state_version(), "changed": [], "preview": outcome.preview,
                    "message": outcome.message}  # fmt: skip
        token = None
        if spec.get("reversible") and outcome.undo is not None:
            token = f"u-{next(self._counter)}"
            self._undo[token] = outcome.undo
            while len(self._undo) > self._max_undo:
                self._undo.popitem(last=False)
        version = bump()
        result: dict[str, Any] = {"status": "ok", "state_version": version, "changed": outcome.changed}
        if token:
            result["undo_token"] = token
        if outcome.message:
            result["message"] = outcome.message
        if outcome.preview is not None:
            result["preview"] = outcome.preview
        return result

    def undo(self, token: str, bump: Callable[[], int]) -> dict[str, Any]:
        fn = self._undo.pop(token, None)
        if fn is None:
            raise WyspError(ErrorCode.UNDO_UNAVAILABLE, "unknown or expired undo token")
        try:
            fn()
        except WyspError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("undo failed")
            raise WyspError(ErrorCode.EXECUTION_FAILED, f"undo failed: {exc}") from exc
        return {"status": "ok", "state_version": bump(), "changed": []}

    def clear_undo(self) -> None:
        self._undo.clear()


class AdapterRuntime:
    """Base class: subclass it, implement observe/get_context and register actions."""

    def __init__(self) -> None:
        self.registry = ActionRegistry()
        self.origin = OriginTagger()
        self._state_version = 0
        self._version_lock = threading.Lock()
        self.client: Any = None  # set by the host after creating the AdapterClient

    # --- state version ---------------------------------------------------------------
    def state_version(self) -> int:
        return self._state_version

    def bump(self) -> int:
        with self._version_lock:
            self._state_version += 1
            return self._state_version

    # --- to implement ----------------------------------------------------------------
    def observe(self, scope: dict[str, Any]) -> dict[str, Any]:
        raise WyspError(ErrorCode.NOT_SUPPORTED, "observe is not implemented")

    def get_context(self) -> dict[str, Any]:
        raise WyspError(ErrorCode.NOT_SUPPORTED, "get_context is not implemented")

    def highlight(self, ref: str, style: str, duration_ms: int) -> dict[str, Any]:
        raise WyspError(ErrorCode.NOT_SUPPORTED, "highlight is not supported")

    def clear_highlight(self) -> dict[str, Any]:
        """Contract 1.1: remove the active persistent highlight. Return {"cleared": bool}."""
        raise WyspError(ErrorCode.NOT_SUPPORTED, "clear_highlight is not supported")

    # --- routing ---------------------------------------------------------------------
    def handle(self, method: str, params: dict[str, Any]) -> Any:
        if method == "adapter.observe":
            return self.observe(params.get("scope") or {"level": "focus"})
        if method == "adapter.get_context":
            return self.get_context()
        if method == "adapter.get_actions":
            return self.registry.specs()
        if method == "adapter.execute":
            with self.origin.wysp():
                return self.registry.execute(params["call"], self.state_version, self.bump)
        if method == "adapter.undo":
            with self.origin.wysp():
                return self.registry.undo(params["token"], self.bump)
        if method == "adapter.highlight":
            return self.highlight(params["ref"], params.get("style", "pulse"), int(params.get("duration_ms", 2500)))
        if method == "adapter.clear_highlight":
            return self.clear_highlight()
        raise WyspError(ErrorCode.METHOD_NOT_FOUND, f"unknown method {method}")

    # --- events ----------------------------------------------------------------------
    def report_change(self, changed: list[str], origin: str | None = None) -> None:
        version = self.bump()
        if self.client is not None:
            self.client.notify(
                "event.state_changed",
                {"state_version": version, "changed": changed, "origin": origin or self.origin.current()},
            )

    def report_selection(self, focus: list[str]) -> None:
        if self.client is not None:
            self.client.notify("event.selection_changed", {"focus": focus})

    def report_highlight_dismissed(self, ref: str) -> None:
        """Contract 1.1: the user interacted with the persistent highlight and it was removed."""
        if self.client is not None:
            self.client.notify("event.highlight_dismissed", {"ref": ref, "reason": "user"})

    def report_user_action(self, kind: str, target: str | None, details: dict[str, Any] | None = None) -> None:
        if self.client is not None:
            self.client.notify(
                "event.user_action",
                {"kind": kind, "target": target, "details": details or {}, "origin": self.origin.current()},
            )
