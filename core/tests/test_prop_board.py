"""Board and Core properties CORE-P3, P9, P10, P11 [core-orchestrator 1.1, 4.x, 8.1]: no adapter, no LLM."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

from hypothesis import given, settings
from hypothesis import strategies as st
from wysp_core.board import MAX_NODES, Board, BoardError, apply_ops, make_patch, normalize_ops
from wysp_core.contract.manifest import Capability
from wysp_core.orchestrator.tools import TOOLS, ToolBox, tool_specs
from wysp_core.store import clear_registered, redact, redact_text, register_secret
from wysp_core.telemetry import Telemetry
from wysp_core.trust.audit import AuditLog

# ------------------------------------------------------------------------------ board operations
NODE_IDS = [f"n{i}" for i in range(90)]  # more than MAX_NODES, so the bound is exercised
small_ids = st.sampled_from(NODE_IDS[:12])
any_ids = st.sampled_from(NODE_IDS)
prov = st.sampled_from(["observed", "inferred", "illustrative"])
text = st.text(alphabet="abcdef ", max_size=8)


def node_op(ids: st.SearchStrategy[str]) -> st.SearchStrategy[dict[str, Any]]:
    return st.builds(
        lambda i, label, p, order: {
            "op": "add_node",
            "node": {"id": i, "kind": "concept", "label": label, "provenance": p, "order": order},
        },
        ids,
        text,
        prov,
        st.none() | st.integers(0, 5),
    )


def edge_op() -> st.SearchStrategy[dict[str, Any]]:
    return st.builds(
        lambda i, s, t: {"op": "add_edge", "edge": {"id": i, "source": s, "target": t, "kind": "link"}},
        st.sampled_from(["e1", "e2", "e3", "e4"]),
        small_ids,
        small_ids,
    )


step_st = st.builds(
    lambda i, t, tg: {"id": i, "index": 0, "text": t, "target": tg},
    st.sampled_from(["s1", "s2", "s3"]),
    text,
    st.none() | small_ids,
)

ops_st: st.SearchStrategy[dict[str, Any]] = st.one_of(
    node_op(small_ids),
    node_op(any_ids),
    st.builds(lambda i: {"op": "remove_node", "id": i}, small_ids),
    edge_op(),
    st.builds(lambda i: {"op": "remove_edge", "id": i}, st.sampled_from(["e1", "e2", "e3", "e4"])),
    st.builds(lambda v: {"op": "set_layout", "layout": v}, st.sampled_from(["stack", "tree", "graph", "sequence"])),
    st.builds(lambda ids: {"op": "set_focus", "ids": ids}, st.lists(small_ids, max_size=4)),
    st.builds(lambda s: {"op": "set_steps", "steps": s}, st.lists(step_st, max_size=3)),
    st.builds(
        lambda i, s: {"op": "update_step", "id": i, "status": s},
        st.sampled_from(["s1", "s2", "s3"]),
        st.sampled_from(["pending", "active", "done", "failed"]),
    ),
    st.builds(
        lambda i, t, tx: {"op": "add_annotation", "annotation": {"id": i, "target": t, "text": tx}},
        st.sampled_from(["a1", "a2"]),
        small_ids,
        text,
    ),
    st.builds(lambda i: {"op": "remove_annotation", "id": i}, st.sampled_from(["a1", "a2"])),
    st.builds(lambda b: {"op": "set_stale", "stale": b}, st.booleans()),
    st.just({"op": "clear"}),
    st.just({"op": "bogus"}),  # rejected ops must not publish anything
)
batches_st = st.lists(st.lists(ops_st, min_size=1, max_size=5), max_size=40)


def run_batches(batches: list[list[dict[str, Any]]]) -> tuple[Board, list[Board], list[Any]]:
    """Mimics Session.apply_board: normalize, apply, publish a patch. Rejected batches publish nothing."""
    board = Board()
    states: list[Board] = [board]
    patches: list[Any] = []
    for ops in batches:
        try:
            ops = normalize_ops(ops)
            after = apply_ops(board, ops)
        except (BoardError, ValueError, KeyError):
            continue
        patches.append(make_patch(board, after, ops))
        board = after
        states.append(board)
    return board, states, patches


@settings(max_examples=50, deadline=None)
@given(batches_st)
def test_prop_board_patch_convergence(batches: list[list[dict[str, Any]]]) -> None:
    """CORE-P3: applying the published patches, in order and over the wire (JSON), to the initial snapshot
    yields the Core's board at its final version."""
    final, _, patches = run_batches(batches)
    replica = Board.model_validate(json.loads(Board().model_dump_json()))  # the snapshot the Panel received
    for patch in patches:
        wire = json.loads(patch.model_dump_json())
        assert wire["base_version"] == replica.version  # patches are contiguous
        replica = apply_ops(replica, wire["ops"])
        assert replica.version == wire["version"]
    assert replica.model_dump(mode="json") == final.model_dump(mode="json")


@settings(max_examples=50, deadline=None)
@given(batches_st)
def test_prop_board_every_prefix_converges(batches: list[list[dict[str, Any]]]) -> None:
    """CORE-P3: convergence holds at every intermediate version, not only the last one."""
    _, states, patches = run_batches(batches)
    replica = Board()
    for patch, expected in zip(patches, states[1:], strict=True):
        replica = apply_ops(replica, patch.ops)
        assert replica.model_dump(mode="json") == expected.model_dump(mode="json")


@settings(max_examples=50, deadline=None)
@given(batches_st)
def test_prop_board_visible_nodes_bounded(batches: list[list[dict[str, Any]]]) -> None:
    """CORE-P9: whatever the operations, the board never holds more than 60 nodes (and ids stay unique)."""
    _, states, _ = run_batches(batches)
    for board in states:
        assert len(board.nodes) <= MAX_NODES == 60
        assert len({n.id for n in board.nodes}) == len(board.nodes)


def test_prop_board_full_board_rejects_the_61st_node() -> None:
    """CORE-P9: a full board refuses a new node, accepts an upsert, and a failed batch changes nothing."""
    board = apply_ops(Board(), [{"op": "add_node", "node": _n(f"n{i}")} for i in range(MAX_NODES)])
    assert len(board.nodes) == MAX_NODES
    try:
        apply_ops(board, [{"op": "add_node", "node": _n("extra")}])
    except BoardError:
        pass
    else:  # pragma: no cover
        raise AssertionError("the 61st node was accepted")
    assert len(board.nodes) == MAX_NODES and board.version == 1
    again = apply_ops(board, [{"op": "add_node", "node": {**_n("n0"), "label": "renamed"}}])
    assert len(again.nodes) == MAX_NODES


def _n(i: str) -> dict[str, Any]:
    return {"id": i, "kind": "concept", "label": i, "provenance": "inferred"}


# ----------------------------------------------------------------------------------- tool filtering
caps_st = st.sets(st.sampled_from(sorted(get_args(Capability))))


@settings(max_examples=50, deadline=None)
@given(caps_st)
def test_prop_tools_follow_capabilities(caps: set[str]) -> None:
    """CORE-P10: the offered tools are exactly those whose required capability is declared (or none required)."""
    offered = {s.name for s in tool_specs(caps)}
    expected = {name for name, (cap, _) in TOOLS.items() if cap is None or cap in caps}
    assert offered == expected
    assert len(offered) == len(tool_specs(caps))  # no duplicate tool
    # capability-gated tools are absent without their capability; free tools are always there
    for name, (cap, _) in TOOLS.items():
        if cap is not None and cap not in caps:
            assert name not in offered
        if cap is None:
            assert name in offered
    # declaring more capabilities never removes a tool
    assert offered <= {s.name for s in tool_specs(caps | {"observe", "execute"})}


@settings(max_examples=50, deadline=None)
@given(caps_st, st.booleans())
def test_prop_toolbox_specs_read_the_manifest(caps: set[str], connected: bool) -> None:
    """CORE-P10: ToolBox.specs derives the capabilities from the connected adapter's manifest (none: no gated tool)."""
    conn = SimpleNamespace(manifest=SimpleNamespace(capabilities=sorted(caps))) if connected else None
    names = {s.name for s in ToolBox(SimpleNamespace(conn=conn)).specs()}  # type: ignore[arg-type]
    effective = caps if connected else set()
    assert names == {n for n, (cap, _) in TOOLS.items() if cap is None or cap in effective}


def test_prop_tools_never_expose_raw_execution() -> None:
    """CORE-P10: no capability set makes the LLM able to run an adapter action directly."""
    every = {s.name for s in tool_specs(set(get_args(Capability)))}
    assert not {"execute", "execute_action", "run_action"} & every


# ----------------------------------------------------------------------------------------- redaction
ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
secret_st = st.text(alphabet=ALNUM, min_size=8, max_size=24)
secrets_st = st.lists(secret_st, min_size=1, max_size=4, unique=True)
filler = st.text(alphabet=ALNUM + " .,:/=", max_size=10)


def leaf(secrets: list[str]) -> st.SearchStrategy[str]:
    return st.lists(st.one_of(filler, st.sampled_from(secrets)), min_size=1, max_size=5).map("".join)


def records_st(secrets: list[str]) -> st.SearchStrategy[Any]:
    return st.recursive(
        leaf(secrets) | st.integers() | st.booleans() | st.none(),
        lambda kids: (
            st.lists(kids, max_size=3)
            | st.dictionaries(st.sampled_from(["a", "b", "text", "headers"]), kids, max_size=3)
        ),
        max_leaves=10,
    )


def text_of(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


@settings(max_examples=50, deadline=None)
@given(st.data())
def test_prop_redact_removes_registered_secrets(data: st.DataObject) -> None:
    """CORE-P11: no substring of redact()'s output equals a registered secret, at any depth of the record."""
    secrets = data.draw(secrets_st)
    record = data.draw(records_st(secrets))
    clear_registered()
    try:
        for s in secrets:
            register_secret(s)
        out = text_of(redact(record))
        for s in secrets:
            assert s not in out
        assert redact(redact(record)) == redact(record)  # idempotent
    finally:
        clear_registered()


@settings(max_examples=50, deadline=None)
@given(st.data())
def test_prop_redact_text_overlapping_secrets(data: st.DataObject) -> None:
    """CORE-P11: secrets that are prefixes or suffixes of each other, repeated or adjacent, are all removed."""
    base = data.draw(secret_st)
    cut = data.draw(st.integers(0, len(base) - 8))
    secrets = list({base, base[cut:], base[: len(base) - cut] if len(base) - cut >= 8 else base})
    pieces = data.draw(st.lists(st.sampled_from([*secrets, "x", " "]), min_size=1, max_size=8))
    clear_registered()
    try:
        for s in secrets:
            register_secret(s)
        out = redact_text("".join(pieces))
        assert all(s not in out for s in secrets)
    finally:
        clear_registered()


@settings(max_examples=50, deadline=None)
@given(st.data())
def test_prop_redact_covers_audit_and_telemetry_records(data: st.DataObject) -> None:
    """CORE-P11: audit records (memory and JSONL) and telemetry records (ring and file) never hold a secret."""
    secrets = data.draw(secrets_st)
    fields = data.draw(
        st.dictionaries(
            st.sampled_from(["detail", "args", "result", "note"]), records_st(secrets), min_size=1, max_size=3
        )
    )
    clear_registered()
    try:
        for s in secrets:
            register_secret(s)
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLog(Path(tmp) / "audit")
            rec = audit.append("proposal", **fields)
            blob = text_of(rec) + text_of(audit.records)
            for f in (Path(tmp) / "audit").glob("*.jsonl"):
                blob += f.read_text(encoding="utf-8")
            tm = Telemetry(level="full", directory=Path(tmp) / "logs")
            tm.emit("llm.request", full=fields, **{"summary": text_of(fields)})
            blob += text_of(list(tm.ring))
            if tm.path is not None:
                tm.close()
                blob += tm.path.read_text(encoding="utf-8")
        for s in secrets:
            assert s not in blob
    finally:
        clear_registered()


def test_prop_redact_pairing_token_from_store(tmp_path, monkeypatch) -> None:
    """CORE-P11: the pairing token created by the store is registered and never survives redact()."""
    from wysp_core.store import load_or_create_token

    monkeypatch.setenv("WYSP_HOME", str(tmp_path))
    clear_registered()
    try:
        token = load_or_create_token()
        register_secret(token)
        assert token not in redact_text(f"auth {token} and {token}")
    finally:
        clear_registered()
