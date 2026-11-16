"""Adapter-contract properties CON-P2..P6, P8..P10 [adapter-contract 3.1, 6.1].

The MockKanban is driven in-process (no WebSocket): `AdapterRuntime.handle` is exactly what the SDK client calls
for every JSON-RPC request, so these properties run in milliseconds and still exercise the real SDK code path.
CON-P7 (postconditions) needs the Core's predicate evaluator and is covered in test_core_with_mock.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from wysp_adapter_sdk import WyspError
from wysp_core.contract import (
    Entity,
    Link,
    Manifest,
    Observation,
    check_observation,
    digest,
)
from wysp_core.contract.observation import MAX_ENTITIES, MAX_OBSERVATION_BYTES
from wysp_mock.kanban import COLUMN_IDS, MockKanban, card_ref, manifest

MANIFEST = Manifest.model_validate(manifest())
KINDS = MANIFEST.kind_names
VOLATILE = MANIFEST.volatile_props
FAST = settings(max_examples=50, deadline=None)
INVALID_CODES = {-32602, -32012, -32013}


# ----------------------------------------------------------------------------------------- helpers
class Recorder:
    """Stands in for the AdapterClient: records every notification the runtime sends."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def notify(self, method: str, params: dict[str, Any] | None = None) -> bool:
        self.events.append((method, params or {}))
        return True


def new_mock(seed_cards: bool = True) -> tuple[MockKanban, Recorder]:
    mock = MockKanban(seed_cards=seed_cards)
    rec = Recorder()
    mock.client = rec
    return mock, rec


def observe(mock: MockKanban) -> Observation:
    return Observation.model_validate(mock.handle("adapter.observe", {"scope": {"level": "full"}}))


def state_digest(mock: MockKanban) -> str:
    return digest(observe(mock), VOLATILE)


def execute(mock: MockKanban, action_id: str, params: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    call = {"action_id": action_id, "params": params, "dry_run": dry_run}
    return mock.handle("adapter.execute", {"call": call})


def pick(mock: MockKanban, index: int) -> str | None:
    ids = sorted(mock.cards, key=lambda c: int(c[1:]))
    return card_ref(ids[index % len(ids)]) if ids else None


title_st = st.text(alphabet="abcdefghij ", min_size=1, max_size=12).filter(lambda s: s.strip() != "")
col_st = st.sampled_from(COLUMN_IDS)
idx_st = st.integers(0, 40)

# an operation = (kind, card index, title, column)
op_st = st.tuples(
    st.sampled_from(
        ["create", "move", "rename", "select", "archive", "describe", "u_create", "u_move", "u_rename", "u_select"]
    ),
    idx_st,
    title_st,
    col_st,
)
ops_st = st.lists(op_st, max_size=25)
REVERSIBLE = ["create", "move", "rename"]
rev_ops_st = st.lists(
    st.tuples(st.sampled_from(REVERSIBLE), idx_st, title_st, col_st),
    max_size=12,
)


def to_call(mock: MockKanban, op: tuple[str, int, str, str]) -> tuple[str, dict[str, Any], bool] | None:
    """Translate an abstract op into (action_id, params, as_user). None when it needs a card and there is none."""
    kind, i, title, col = op
    user = kind.startswith("u_")
    kind = kind.removeprefix("u_")
    ref = pick(mock, i)
    if kind == "create":
        return "create_card", {"title": title, "column": col}, user
    if ref is None:
        return None
    if kind == "move":
        return "move_card", {"card": ref, "column": col}, user
    if kind == "rename":
        return "rename_card", {"card": ref, "title": title}, user
    if kind == "select":
        return "select_card", {"card": ref}, user
    if kind == "archive":
        return "archive_card", {"card": ref}, user
    return "describe_card", {"card": ref}, user


def run_ops(mock: MockKanban, ops: list[tuple[str, int, str, str]]) -> None:
    for op in ops:
        call = to_call(mock, op)
        if call is None:
            continue
        action_id, params, user = call
        if user:
            mock.simulate_user(action_id, params)
        else:
            execute(mock, action_id, params)


# ------------------------------------------------------------------------------------------- CON-P2
@FAST
@given(ops_st)
def test_prop_observation_integrity_after_any_actions(ops: list[tuple[str, int, str, str]]) -> None:
    """CON-P2: after any sequence of actions and user changes, parent, link, focus refs resolve, refs are unique and
    every kind is declared."""
    mock, _ = new_mock()
    run_ops(mock, ops)
    obs = observe(mock)
    assert check_observation(obs, KINDS) == []
    assert len(obs.entities) <= MAX_ENTITIES


@FAST
@given(st.lists(st.text(alphabet="ab", min_size=1, max_size=3), max_size=6), st.data())
def test_prop_check_observation_detects_every_violation(extra: list[str], data: st.DataObject) -> None:
    """CON-P2: the kit's checker flags dangling parents, links and focus, duplicate refs and undeclared kinds."""
    mock, _ = new_mock()
    base = observe(mock)
    assert check_observation(base, KINDS) == []
    broken = data.draw(st.sampled_from(["parent", "link", "focus", "dup", "kind"]))
    ents = list(base.entities)
    links: list[Link] = []
    focus: list[str] = []
    ghost = "mock://card/ghost" + "".join(extra)
    if broken == "parent":
        ents.append(Entity(ref="mock://card/zz", kind="card", label="x", parent=ghost))
    elif broken == "link":
        links.append(Link.model_validate({"from": ents[0].ref, "to": ghost, "kind": "rel"}))
    elif broken == "focus":
        focus.append(ghost)
    elif broken == "dup":
        ents.append(ents[1])
    else:
        ents.append(Entity(ref="mock://card/zz", kind="widget", label="x", parent=ents[0].ref))
    bad = base.model_copy(update={"entities": ents, "links": links, "focus": focus})
    assert check_observation(bad, KINDS) != []


# ------------------------------------------------------------------------------------------- CON-P3
@FAST
@given(ops_st)
def test_prop_refs_and_digest_stable_without_change(ops: list[tuple[str, int, str, str]]) -> None:
    """CON-P3: two observations with no intervening change have the same refs and the same digest."""
    mock, _ = new_mock()
    run_ops(mock, ops)
    a, b = observe(mock), observe(mock)
    assert [e.ref for e in a.entities] == [e.ref for e in b.entities]
    assert digest(a, VOLATILE) == digest(b, VOLATILE)
    assert a.state_version == b.state_version


@FAST
@given(ops_st, st.sampled_from(["create_card", "rename_card"]), title_st)
def test_prop_read_only_and_dry_run_calls_keep_the_digest(
    ops: list[tuple[str, int, str, str]], action_id: str, title: str
) -> None:
    """CON-P3: describe and dry-run execute do not change the state, so the digest is stable across them."""
    mock, _ = new_mock()
    run_ops(mock, ops)
    before = state_digest(mock)
    ref = pick(mock, 0)
    if ref is not None:
        execute(mock, "describe_card", {"card": ref})
    params = {"title": title, "column": "todo"} if action_id == "create_card" else {"card": ref, "title": title}
    if action_id == "create_card" or ref is not None:
        execute(mock, action_id, params, dry_run=True)
    assert state_digest(mock) == before


# ------------------------------------------------------------------------------------------- CON-P4
prop_val = st.one_of(st.integers(-5, 5), st.text(alphabet="xyz", max_size=3), st.booleans(), st.none())
entity_st = st.fixed_dictionaries(
    {"kind": st.sampled_from(["a", "b"]), "v": prop_val, "tick": st.integers(0, 10**6), "w": prop_val}
)


def synth(rows: list[dict[str, Any]], link_pairs: list[tuple[int, int]]) -> Observation:
    ents = [
        Entity(ref=f"t://e/{i}", kind=r["kind"], label=f"l{i}", props={"v": r["v"], "tick": r["tick"], "w": r["w"]})
        for i, r in enumerate(rows)
    ]
    links = [
        Link.model_validate({"from": f"t://e/{a % len(rows)}", "to": f"t://e/{b % len(rows)}", "kind": "rel"})
        for a, b in link_pairs
    ]
    return Observation(observation_id="o", state_version=1, captured_at=datetime.now(UTC), entities=ents, links=links)


@FAST
@given(
    st.lists(entity_st, min_size=1, max_size=8),
    st.lists(st.tuples(st.integers(0, 20), st.integers(0, 20)), max_size=6),
    st.randoms(use_true_random=False),
    st.integers(0, 10**6),
)
def test_prop_digest_invariant_under_permutation_and_volatile(rows, link_pairs, rnd, new_tick) -> None:
    """CON-P4: permuting entities or links, or changing only volatile props, leaves the digest unchanged."""
    obs = synth(rows, link_pairs)
    ents, links = list(obs.entities), list(obs.links)
    rnd.shuffle(ents)
    rnd.shuffle(links)
    ents = [e.model_copy(update={"props": {**e.props, "tick": new_tick}}) for e in ents]
    other = obs.model_copy(
        update={"entities": ents, "links": links, "observation_id": "zzz", "state_version": 99, "focus": []}
    )
    assert digest(other, ["tick"]) == digest(obs, ["tick"])


@FAST
@given(
    st.lists(entity_st, min_size=1, max_size=8),
    st.integers(0, 20),
    st.sampled_from(["v", "w", "new", "kind", "parent"]),
)
def test_prop_digest_changes_with_non_volatile_data(rows, which, what) -> None:
    """CON-P4: changing a non-volatile prop (or adding one, or the kind) changes the digest."""
    obs = synth(rows, [])
    i = which % len(obs.entities)
    ent = obs.entities[i]
    if what == "kind":
        changed = ent.model_copy(update={"kind": ent.kind + "x"})
    elif what == "parent":
        changed = ent.model_copy(update={"parent": "t://e/root"})
    elif what == "new":
        changed = ent.model_copy(update={"props": {**ent.props, "extra": 1}})
    else:
        old = ent.props[what]
        new = "changed" if not isinstance(old, str) else 12345
        changed = ent.model_copy(update={"props": {**ent.props, what: new}})
    ents = list(obs.entities)
    ents[i] = changed
    assert digest(obs.model_copy(update={"entities": ents}), ["tick"]) != digest(obs, ["tick"])


@FAST
@given(ops_st, st.randoms(use_true_random=False))
def test_prop_mock_digest_invariant_under_permutation(ops, rnd) -> None:
    """CON-P4: on real mock observations, shuffling entities keeps the digest."""
    mock, _ = new_mock()
    run_ops(mock, ops)
    obs = observe(mock)
    ents = list(obs.entities)
    rnd.shuffle(ents)
    assert digest(obs.model_copy(update={"entities": ents}), VOLATILE) == digest(obs, VOLATILE)


# ------------------------------------------------------------------------------------------- CON-P5
BAD_REF = "mock://card/c99999"
bad_params_st = st.one_of(
    # target does not exist (valid shape)
    st.tuples(st.just("move_card"), st.just({"card": BAD_REF, "column": "todo"})),
    st.tuples(st.just("rename_card"), st.just({"card": BAD_REF, "title": "x"})),
    st.tuples(st.just("select_card"), st.just({"card": BAD_REF})),
    st.tuples(st.just("archive_card"), st.just({"card": BAD_REF})),
    st.tuples(st.just("describe_card"), st.just({"card": BAD_REF})),
    # schema violations
    st.tuples(st.just("create_card"), st.just({})),
    st.tuples(st.just("create_card"), st.just({"title": "", "column": "todo"})),
    st.tuples(st.just("create_card"), st.just({"title": "x" * 81, "column": "todo"})),
    st.tuples(st.just("create_card"), st.just({"title": "x", "column": "nowhere"})),
    st.tuples(st.just("create_card"), st.just({"title": 5, "column": "todo"})),
    st.tuples(st.just("create_card"), st.just({"title": "x", "column": "todo", "extra": 1})),
    st.tuples(st.just("move_card"), st.just({"card": "not-a-ref", "column": "todo"})),
    st.tuples(st.just("move_card"), st.just({"card": None, "column": "todo"})),
    st.tuples(st.just("rename_card"), st.just({"title": "x"})),
    st.tuples(st.just("select_card"), st.just({"card": ["mock://card/c1"]})),
    st.tuples(st.just("archive_card"), st.just({"card": "mock://card/c1", "force": True})),
)


@FAST
@given(ops_st, bad_params_st, st.booleans())
def test_prop_invalid_calls_do_not_change_state(ops, bad, dry_run) -> None:
    """CON-P5: a call with invalid params or a missing target fails with -32602/-32012/-32013 and changes nothing."""
    mock, rec = new_mock()
    run_ops(mock, ops)
    before, version, n_events = state_digest(mock), mock.state_version(), len(rec.events)
    action_id, params = bad
    with pytest.raises(WyspError) as caught:
        execute(mock, action_id, params, dry_run=dry_run)
    assert caught.value.code in INVALID_CODES
    assert state_digest(mock) == before
    assert mock.state_version() == version and len(rec.events) == n_events


# ------------------------------------------------------------------------------------------- CON-P6
@FAST
@given(ops_st, rev_ops_st)
def test_prop_undo_round_trip(prefix, seq) -> None:
    """CON-P6: undoing successful reversible actions in reverse order restores the initial digest."""
    mock, _ = new_mock()
    run_ops(mock, prefix)
    initial = state_digest(mock)
    tokens: list[str] = []
    for op in seq:
        call = to_call(mock, op)
        if call is None:
            continue
        result = execute(mock, call[0], call[1])
        assert result["status"] == "ok" and result.get("undo_token")
        tokens.append(result["undo_token"])
    for token in reversed(tokens):
        mock.handle("adapter.undo", {"token": token})
    assert state_digest(mock) == initial


def test_prop_undo_token_is_single_use() -> None:
    """CON-P6: a token undoes once; reusing it fails with -32015 and changes nothing."""
    mock, _ = new_mock()
    token = execute(mock, "create_card", {"title": "t", "column": "todo"})["undo_token"]
    mock.handle("adapter.undo", {"token": token})
    after = state_digest(mock)
    with pytest.raises(WyspError) as caught:
        mock.handle("adapter.undo", {"token": token})
    assert caught.value.code == -32015
    assert state_digest(mock) == after


# ------------------------------------------------------------------------------------------- CON-P8
@FAST
@given(ops_st, st.lists(st.booleans(), max_size=10))
def test_prop_state_version_is_monotonic(ops, undo_flags) -> None:
    """CON-P8: across results, observations and events, state_version never decreases and strictly increases on
    each state event."""
    mock, rec = new_mock()
    seen: list[int] = []
    for op in ops:
        call = to_call(mock, op)
        if call is None:
            continue
        action_id, params, user = call
        if user:
            mock.simulate_user(action_id, params)
        else:
            result = execute(mock, action_id, params)
            seen.append(result["state_version"])
            if result.get("undo_token") and undo_flags and undo_flags[len(seen) % len(undo_flags)]:
                seen.append(mock.handle("adapter.undo", {"token": result["undo_token"]})["state_version"])
        seen.append(observe(mock).state_version)
    mock.report_change([])  # a state event with nothing in particular
    assert seen == sorted(seen)
    state_versions = [p["state_version"] for m, p in rec.events if m == "event.state_changed"]
    assert all(b > a for a, b in zip(state_versions, state_versions[1:], strict=False))
    if seen and state_versions:
        assert state_versions[-1] >= seen[-1]


@FAST
@given(ops_st)
def test_prop_each_successful_change_bumps_the_version(ops) -> None:
    """CON-P8: a successful execute or undo returns a strictly larger state_version than before it."""
    mock, _ = new_mock()
    run_ops(mock, ops)
    before = mock.state_version()
    result = execute(mock, "create_card", {"title": "n", "column": "doing"})
    assert result["state_version"] > before
    undone = mock.handle("adapter.undo", {"token": result["undo_token"]})
    assert undone["state_version"] > result["state_version"]


# ------------------------------------------------------------------------------------------- CON-P9
def reset_window(mock: MockKanban) -> None:
    """Let the 'caused by Wysp' window lapse, as it does between a host's own events."""
    mock.origin._until = 0.0  # noqa: SLF001 - test helper


@FAST
@given(ops_st, title_st)
def test_prop_origin_tagging(ops, title) -> None:
    """CON-P9: events for a change caused by execute/undo carry origin 'wysp'; simulate_user events carry 'user',
    even right after a Wysp action."""
    mock, rec = new_mock()
    run_ops(mock, ops)
    reset_window(mock)

    # execute: the host reports the change it just made while the execute is still the cause
    rec.events.clear()
    result = execute(mock, "create_card", {"title": title, "column": "todo"})
    mock.report_change(result["changed"])
    mock.report_user_action("create_card", result["changed"][0])
    # undo, same rule
    mock.handle("adapter.undo", {"token": result["undo_token"]})
    mock.report_change(result["changed"])
    assert rec.events and all(p["origin"] == "wysp" for _, p in rec.events)

    # a user change made immediately afterwards (inside the window) is still the user's
    rec.events.clear()
    mock.simulate_user("create_card", {"title": title, "column": "doing"})
    mock.simulate_user("select_card", {"card": pick(mock, 0)})
    assert {m for m, _ in rec.events} >= {"event.state_changed", "event.user_action"}
    assert all(p["origin"] == "user" for m, p in rec.events if m in ("event.state_changed", "event.user_action"))


def test_prop_origin_is_user_once_the_window_lapses() -> None:
    """CON-P9: the 'wysp' tag is only a short window; later changes report 'user'."""
    mock, rec = new_mock()
    execute(mock, "create_card", {"title": "a", "column": "todo"})
    assert mock.origin.current() == "wysp"
    reset_window(mock)
    mock.report_change(["mock://card/c1"])
    assert rec.events[-1][1]["origin"] == "user"


# ------------------------------------------------------------------------------------------ CON-P10
many_st = st.integers(min_value=0, max_value=900)


@settings(max_examples=12, deadline=None)
@given(many_st, st.integers(0, 40))
def test_prop_observation_size_limits(n_cards: int, selected: int) -> None:
    """CON-P10: an observation has at most 500 entities and 256 KB; when truncated, counts[kind] is at least the
    number of returned entities of that kind."""
    mock, _ = new_mock(seed_cards=False)
    for i in range(n_cards):
        mock._add_card(f"card {i} " + "x" * 70, COLUMN_IDS[i % 3])  # noqa: SLF001 - test helper
    if n_cards:
        mock.selected = f"c{(selected % n_cards) + 1}"
    raw = mock.handle("adapter.observe", {"scope": {"level": "full"}})
    obs = Observation.model_validate(raw)
    assert len(obs.entities) <= MAX_ENTITIES
    assert len(obs.model_dump_json().encode()) <= MAX_OBSERVATION_BYTES
    assert check_observation(obs, KINDS) == []
    returned: dict[str, int] = {}
    for e in obs.entities:
        returned[e.kind] = returned.get(e.kind, 0) + 1
    for kind, n in returned.items():
        assert obs.counts.get(kind, 0) >= n
    if n_cards + 4 > MAX_ENTITIES:
        assert obs.truncated is True
        assert obs.counts["card"] == n_cards
    else:
        assert obs.truncated is False and len(obs.entities) == n_cards + 4


@FAST
@given(st.integers(MAX_ENTITIES + 1, MAX_ENTITIES + 30))
def test_prop_check_observation_flags_oversized_observations(n: int) -> None:
    """CON-P10: the kit's checker rejects an observation with more than 500 entities."""
    ents = [Entity(ref=f"t://e/{i}", kind="a", label="x") for i in range(n)]
    obs = Observation(observation_id="o", state_version=1, captured_at=datetime.now(UTC), entities=ents)
    assert any("exceed" in p for p in check_observation(obs))
