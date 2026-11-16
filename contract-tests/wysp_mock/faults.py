"""A mock Kanban adapter that reports its changes like a real one, with deliberate faults [adapter-contract 10].

The Contract Test Kit must FAIL on each fault below (tests/test_kit_faults.py). With no fault, this adapter is the
well-behaved reference of the online harness: `wysp-contract --fixture contract-tests/fixtures/mock/contract.fixture.yaml`.

    wrong_origin             events caused by Wysp are tagged `user`                     CON-P9    events
    undo_noop                undo returns ok but restores nothing                        CON-P6    undo_round_trip
    undeclared_kind          an entity kind the manifest does not declare                CON-P2    observe_integrity
    postcondition_lie        execute returns ok without changing anything                CON-P7    postconditions
    state_version_regression observations report a version behind the last result        CON-P8    state_version
    dirty_invalid            an invalid call changes the state before it is rejected     CON-P5    invalid_calls
    dry_run_mutates          dry_run really executes                                     5.x       dry_run
    unstable_digest          an undeclared volatile prop changes at every observation    CON-P3    ref_stability

`latency_ms=300` in the fixture's `faults` (or `--fault latency_ms=300`) is not a fault: it delays every request and the\nkit must stay green.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from typing import Any

from wysp_adapter_sdk import AdapterClient, WyspError

from .kanban import BOARD, MockKanban, manifest

FAULTS = {
    "wrong_origin",
    "undo_noop",
    "undeclared_kind",
    "postcondition_lie",
    "state_version_regression",
    "dirty_invalid",
    "dry_run_mutates",
    "unstable_digest",
}


class KitKanban(MockKanban):
    def __init__(self, faults: list[str] | tuple[str, ...] = (), latency_s: float = 0.0) -> None:
        super().__init__(latency_s=latency_s)
        unknown = set(faults) - FAULTS
        if unknown:
            raise ValueError(f"unknown faults {sorted(unknown)}; known: {sorted(FAULTS)}")
        self.faults = set(faults)
        self._clock = itertools.count(1)

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        if self.latency_s:
            time.sleep(self.latency_s)
        call = params.get("call") if method == "adapter.execute" else None
        dry = bool(call and call.get("dry_run"))
        if call is not None and dry and "dry_run_mutates" in self.faults:
            result = super().handle(method, {**params, "call": {**call, "dry_run": False}})
            result.pop("undo_token", None)
            return {**result, "changed": []}  # claims to have changed nothing
        if call is not None and "dirty_invalid" in self.faults and call.get("action_id") == "move_card":
            try:
                return self._after(method, call, dry, super().handle(method, params))
            except WyspError:
                self._add_card("ghost", "todo")  # the state moves before the call is rejected
                raise
        result = super().handle(method, params)
        if method == "adapter.observe":
            result = self._tamper(result)
        return self._after(method, call, dry, result)

    def _tamper(self, obs: dict[str, Any]) -> dict[str, Any]:
        if "undeclared_kind" in self.faults:
            obs["entities"][-1]["kind"] = "unicorn"
        if "state_version_regression" in self.faults:
            obs["state_version"] = max(0, obs["state_version"] - 2)
        if "unstable_digest" in self.faults:
            obs["entities"][0]["props"]["undeclared_clock"] = next(self._clock)
        return obs

    def _after(self, method: str, call: dict[str, Any] | None, dry: bool, result: Any) -> Any:
        if method == "adapter.execute" and not dry and call is not None:
            if "postcondition_lie" in self.faults and call["action_id"] in ("create_card", "move_card", "rename_card"):
                self._forget_last(result)
            if "undo_noop" in self.faults and result.get("undo_token"):
                self.registry._undo[result["undo_token"]] = lambda: None  # noqa: SLF001
            self.report_change(
                result.get("changed") or [BOARD], origin="user" if "wrong_origin" in self.faults else None
            )
        elif method == "adapter.undo":
            self.report_change([BOARD], origin="user" if "wrong_origin" in self.faults else None)
        return result

    def _forget_last(self, result: dict[str, Any]) -> None:
        """Undo the change but keep reporting success (the token is dropped: nothing is left to undo)."""
        token = result.pop("undo_token", None)
        undo: Callable[[], None] | None = self.registry._undo.pop(token, None) if token else None  # noqa: SLF001
        if undo is not None:
            undo()


def start(url: str, token: str, faults: list[str]) -> Callable[[], None]:
    """In-process launcher entry point (`launch.adapter: wysp_mock.faults:start`). Return the stop function."""
    latency = next((float(f.split("=", 1)[1]) / 1000 for f in faults if f.startswith("latency_ms=")), 0.0)
    app = KitKanban([f for f in faults if not f.startswith("latency_ms=")], latency_s=latency)
    client = AdapterClient(manifest(), url, token, app.handle, state_version=app.state_version)
    app.client = client
    client.start()

    def stop() -> None:
        client.stop()

    return stop
