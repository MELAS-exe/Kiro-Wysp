"""The Kit's observation property checks [adapter-contract 9.1]: they pass on the mock and catch broken adapters."""

from __future__ import annotations

import copy
import itertools
from typing import Any

from wysp_contract.checks import (
    check_observe_integrity,
    check_postconditions,
    check_ref_stability,
    run_observation_checks,
)
from wysp_core.contract import Manifest
from wysp_mock.kanban import MockKanban, manifest

MANIFEST = Manifest.model_validate(manifest())
CALLS = [
    {"action_id": "create_card", "params": {"title": "Kit card", "column": "todo"}},
    {"action_id": "move_card", "params": {"card": "mock://card/c1", "column": "done"}},
    {"action_id": "rename_card", "params": {"card": "mock://card/c2", "title": 'it\'s "quoted"'}},
    {"action_id": "select_card", "params": {"card": "mock://card/c1"}},
    {"action_id": "archive_card", "params": {"card": "mock://card/c3"}},
]


def tamper(mutate_observe=None, mutate_execute=None):
    mock = MockKanban()

    def request(method: str, params: dict[str, Any]) -> Any:
        result = mock.handle(method, params)
        if method == "adapter.observe" and mutate_observe:
            result = mutate_observe(copy.deepcopy(result))
        if method == "adapter.execute" and mutate_execute:
            return mutate_execute(mock, params, result)
        return result

    return request


def test_the_mock_passes_every_check() -> None:
    findings = run_observation_checks(MockKanban().handle, MANIFEST, CALLS)
    assert [f.check for f in findings] == ["observe_integrity", "ref_stability", "postconditions"]
    assert all(f.ok for f in findings), [str(f) for f in findings]


def test_integrity_check_catches_a_dangling_parent_and_an_undeclared_kind() -> None:
    def dangling(obs):
        obs["entities"][-1]["parent"] = "mock://nowhere/x"
        return obs

    def undeclared(obs):
        obs["entities"][-1]["kind"] = "unicorn"
        return obs

    assert not check_observe_integrity(tamper(dangling), MANIFEST).ok
    assert not check_observe_integrity(tamper(undeclared), MANIFEST).ok


def test_size_check_catches_too_many_entities_too_many_bytes_and_dishonest_counts() -> None:
    def too_many(obs):
        base = obs["entities"][0]
        obs["entities"] = [{**base, "ref": f"mock://card/x{i}", "parent": None} for i in range(501)]
        obs["links"], obs["focus"] = [], []
        return obs

    def too_big(obs):
        obs["entities"][0]["props"]["blob"] = "x" * (257 * 1024)
        return obs

    def bad_counts(obs):
        obs["truncated"], obs["counts"] = True, {}
        return obs

    for mutate in (too_many, too_big, bad_counts):
        assert not check_observe_integrity(tamper(mutate), MANIFEST).ok, mutate.__name__


def test_stability_check_catches_an_undeclared_volatile_prop_and_changing_refs() -> None:
    ticks = itertools.count()

    def volatile(obs):
        obs["entities"][0]["props"]["undeclared_clock"] = next(ticks)
        return obs

    def new_refs(obs):
        obs["entities"][0]["ref"] = f"mock://card/g{next(ticks)}"
        obs["entities"][0]["parent"] = None
        obs["links"], obs["focus"] = [], []
        return obs

    assert not check_ref_stability(tamper(volatile), MANIFEST).ok
    assert not check_ref_stability(tamper(new_refs), MANIFEST).ok


def test_postcondition_check_catches_an_action_that_reports_success_without_acting() -> None:
    def lies(mock, params, result):
        call = params["call"]
        if call["action_id"] == "create_card":  # report ok, but undo straight away
            mock.handle("adapter.undo", {"token": result["undo_token"]})
            return {**result, "undo_token": None}
        return result

    assert check_postconditions(tamper(mutate_execute=lies), CALLS).ok is False
    assert check_postconditions(tamper(), CALLS).ok


def test_postcondition_check_reports_a_failing_safe_call() -> None:
    finding = check_postconditions(
        MockKanban().handle, [{"action_id": "move_card", "params": {"card": "mock://card/c99", "column": "done"}}]
    )
    assert not finding.ok and "-32012" in finding.detail
