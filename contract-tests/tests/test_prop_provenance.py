"""Provenance properties CORE-P1, CORE-P2, CORE-P12 [core-orchestrator 6.1].

A real `Session` and `ToolBox` (board, projection, provenance validator) run against the in-process MockKanban,
through a connection stub that returns what `AdapterConnection.observe` would. No WebSocket, no LLM.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from wysp_core.board import project
from wysp_core.contract import ActionCall, ActionResult, ActionSpec, Context, Manifest, Observation, Scope, WyspError
from wysp_core.gateway.registry import AdapterRegistry
from wysp_core.llm import ScriptedLLM
from wysp_core.orchestrator.tools import ToolBox
from wysp_core.session.bus import EventBus
from wysp_core.session.session import Session
from wysp_core.trust.audit import AuditLog
from wysp_core.ui_api.hub import UiHub
from wysp_mock.kanban import MockKanban, card_ref, col_ref, manifest

FAST = settings(max_examples=50, deadline=None)
MANIFEST = Manifest.model_validate(manifest())


class _Client:
    def notify(self, method: str, params: dict[str, Any] | None = None) -> bool:
        return True


class FakeConn:
    """Stands in for AdapterConnection: observations come straight from the in-process mock."""

    adapter_id = "mock-kanban"
    connected = True

    def __init__(self, mock: MockKanban) -> None:
        self.mock = mock
        self.manifest = MANIFEST
        self.tamper: Callable[[ActionCall], ActionCall] | None = None
        self.tamper_result: Callable[[ActionResult], ActionResult] | None = None
        self.returned: set[str] = set()  # every ref any observation ever returned

    async def execute(self, call: ActionCall) -> ActionResult:
        """What the application does with a call. `tamper` lets a test make the adapter misreport or misbehave."""
        if self.tamper is not None:
            call = self.tamper(call)
        raw = self._rpc("adapter.execute", {"call": call.model_dump(mode="json")})
        result = ActionResult.model_validate(raw)
        return self.tamper_result(result) if self.tamper_result is not None else result

    async def undo(self, token: str) -> ActionResult:
        return ActionResult.model_validate(self._rpc("adapter.undo", {"token": token}))

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        try:
            return self.mock.handle(method, params)
        except Exception as exc:  # the SDK and the Core each define a WyspError
            code = getattr(exc, "code", None)
            if code is None:
                raise
            raise WyspError(code, getattr(exc, "message", str(exc))) from exc

    async def get_actions(self) -> list[ActionSpec]:
        return [ActionSpec.model_validate(a) for a in self.mock.handle("adapter.get_actions", {})]

    async def get_context(self) -> Context:
        return Context.model_validate(self.mock.handle("adapter.get_context", {}))

    async def observe(self, scope: Scope | None = None) -> Observation:
        scope = scope or Scope()
        raw = self.mock.handle("adapter.observe", {"scope": scope.model_dump(mode="json", exclude_none=True)})
        obs = Observation.model_validate(raw)
        self.returned.update(e.ref for e in obs.entities)
        return obs


def make_session() -> tuple[Session, FakeConn]:
    mock = MockKanban(seed_cards=True)
    mock.client = _Client()
    bus = EventBus()
    registry = AdapterRegistry(bus)
    conn = FakeConn(mock)
    registry.add(conn)  # type: ignore[arg-type]
    session = Session(registry, bus, UiHub(), AuditLog(None), ScriptedLLM([]), survey=False)
    return session, conn


def run(coro: Awaitable[Any]) -> Any:
    return asyncio.run(coro)  # type: ignore[arg-type]


def observed_nodes(session: Session) -> list[Any]:
    return [n for n in session.board.nodes if n.provenance == "observed"]


# ----------------------------------------------------------------------------------- strategies
word = st.text(alphabet="abcdefghij ", min_size=1, max_size=10)
json_value = st.recursive(
    st.none() | st.booleans() | st.integers(-5, 5) | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=4), inner, max_size=3),
    max_leaves=6,
)
claims = st.sampled_from(["observed", "inferred", "illustrative", "OBSERVED", "", None, 1, True])


def ref_pool(draw_index: int) -> str:
    return card_ref(f"c{draw_index}")


refs_st = st.lists(
    st.one_of(
        st.integers(1, 12).map(lambda i: card_ref(f"c{i}")),  # seeded cards, and ids that may not exist
        st.sampled_from(["mock://board", col_ref("todo"), "mock://nothing/here", "c:fake", "n:mock://card/c1"]),
    ),
    max_size=6,
)

tool_call_st = st.one_of(
    st.tuples(st.just("observe"), st.fixed_dictionaries({"level": st.sampled_from(["summary", "focus", "full"])})),
    st.tuples(
        st.just("show_entities"),
        st.fixed_dictionaries(
            {
                "refs": refs_st.filter(bool),
                "include_children": st.booleans(),
                "replace": st.booleans(),
                "layout": st.sampled_from(["graph", "tree", "stack", "sequence", "nonsense"]),
            }
        ),
    ),
    st.tuples(
        st.just("add_concept"),
        st.fixed_dictionaries(
            {
                "items": st.lists(
                    st.fixed_dictionaries(
                        {"label": word, "provenance": claims, "kind": st.sampled_from(["concept", "step", "example"])}
                    ),
                    min_size=1,
                    max_size=3,
                ),
                "attach_to": refs_st.map(lambda r: r[0] if r else "x"),
            }
        ),
    ),
    st.tuples(
        st.just("annotate"),
        st.fixed_dictionaries(
            {"target": refs_st.map(lambda r: r[0] if r else "x"), "text": word, "provenance": claims}
        ),
    ),
    # a model writing board operations directly is not possible, but the validator must hold if Core code does
    st.tuples(
        st.just("raw_node"),
        st.fixed_dictionaries(
            {"ref": refs_st.map(lambda r: r[0] if r else None), "id": st.integers(0, 6).map(lambda i: f"r{i}")}
        ),
    ),
)
mock_change_st = st.tuples(st.sampled_from(["create", "archive", "rename", "none"]), st.integers(1, 12), word)


async def apply_mock_change(conn: FakeConn, change: tuple[str, int, str]) -> None:
    kind, i, title = change
    mock = conn.mock
    if kind == "create":
        mock.simulate_user("create_card", {"title": title, "column": "todo"})
    elif kind == "archive" and f"c{i}" in mock.cards:
        mock.simulate_user("archive_card", {"card": card_ref(f"c{i}")})
    elif kind == "rename" and f"c{i}" in mock.cards:
        mock.simulate_user("rename_card", {"card": card_ref(f"c{i}"), "title": title})


async def call_tool(session: Session, tools: ToolBox, name: str, args: dict[str, Any]) -> None:
    if name == "raw_node":  # a node that claims `observed` for a ref, straight to the board
        node = {
            "id": args["id"],
            "ref": args["ref"],
            "kind": "card",
            "label": "claimed",
            "provenance": "observed",
        }
        await session.apply_board([{"op": "add_node", "node": node}])
        return
    await tools.call(name, args)


# ------------------------------------------------------------------------------------- CORE-P1
@FAST
@given(st.lists(st.tuples(tool_call_st, mock_change_st), max_size=10))
def test_prop_core_p1_observed_nodes_are_backed_by_observations(steps) -> None:
    """CORE-P1: after any sequence of tool calls and application changes, every board node with provenance
    `observed` has a ref in the session's observation index, and the index holds only refs an adapter returned."""

    async def scenario() -> None:
        session, conn = make_session()
        tools = ToolBox(session)
        for (name, args), change in steps:
            await apply_mock_change(conn, change)
            await call_tool(session, tools, name, args)
            index = session.observed_refs
            assert index <= conn.returned, "the index holds a ref no observation returned"
            for node in observed_nodes(session):
                assert node.ref is not None and node.ref in index, f"{node.id} is observed without an observation"
            for edge in session.board.edges:
                if edge.provenance == "observed":
                    assert edge.id.startswith("e:") and edge.source in {n.id for n in session.board.nodes}

    run(scenario())


@FAST
@given(refs_st, st.integers(0, 3))
def test_prop_core_p1_unobserved_claims_are_downgraded(refs: list[str], observed_count: int) -> None:
    """CORE-P1: a node claiming `observed` for a ref nobody observed ends up `inferred` without a ref."""

    async def scenario() -> None:
        session, conn = make_session()
        for ref in refs[:observed_count]:
            session.observed_refs.add(ref)
        await session.apply_board(
            [
                {
                    "op": "add_node",
                    "node": {"id": f"k{i}", "ref": r, "kind": "card", "label": "x", "provenance": "observed"},
                }
                for i, r in enumerate(refs)
            ]
        )
        backed = set(refs[:observed_count])
        for node in session.board.nodes:
            if node.ref in backed:
                assert node.provenance == "observed"
            else:
                assert node.provenance == "inferred" and node.ref is None

    run(scenario())


# ------------------------------------------------------------------------------------- CORE-P2
item_st = st.fixed_dictionaries(
    {"label": word},
    optional={
        "provenance": st.one_of(claims, json_value),
        "kind": st.sampled_from(["concept", "step", "example", "card"]) | st.text(max_size=5),
        "key": st.text(alphabet="abc-_01", max_size=6),
        "attach_to": st.sampled_from(["n:mock://card/c1", "mock://card/c1", "c:a", "zz"]),
        "ref": st.sampled_from(["mock://card/c1", "mock://board"]),  # an LLM trying to smuggle a ref
        "confidence": st.floats(0, 5),
        "observed": st.booleans(),
    },
)
add_concept_args = st.one_of(
    st.fixed_dictionaries({"items": st.lists(item_st, max_size=14)}, optional={"provenance": claims}),
    st.builds(lambda i: {**i}, item_st),  # single-node form: top-level label and provenance
)
annotate_args = st.fixed_dictionaries(
    {
        "target": st.sampled_from(["n:mock://card/c1", "mock://card/c2", "c:a", "zz", "mock://nope"]),
        "text": word,
    },
    optional={"provenance": st.one_of(claims, json_value), "ref": st.just("mock://card/c1")},
)


@FAST
@given(
    st.lists(
        st.one_of(
            st.tuples(st.just("add_concept"), add_concept_args),
            st.tuples(st.just("annotate"), annotate_args),
            st.tuples(st.just("show_entities"), st.just({"refs": ["mock://card/c1", "mock://card/c2"]})),
        ),
        min_size=1,
        max_size=6,
    )
)
def test_prop_core_p2_the_llm_cannot_create_observed_facts(calls) -> None:
    """CORE-P2: whatever add_concept and annotate receive, even a claim of `observed`, what they add is `inferred`
    or `illustrative`, carries no ref, and only show_entities (projection) produces `observed` nodes."""

    async def scenario() -> None:
        session, _ = make_session()
        tools = ToolBox(session)
        await session.observe()  # the application was observed: a smuggled ref would be accepted if it was honoured
        for name, args in calls:
            before_nodes = {n.id for n in session.board.nodes}
            before_notes = {a.id for a in session.board.annotations}
            await tools.call(name, args)
            projected = name == "show_entities"
            for node in session.board.nodes:
                if node.id in before_nodes and not projected:
                    continue
                if name != "show_entities" or node.id not in before_nodes:
                    if projected:
                        assert node.provenance == "observed" and node.id.startswith("n:")
                    else:
                        assert node.provenance in ("inferred", "illustrative"), node
                        assert node.ref is None and node.id.startswith("c:")
            for ann in session.board.annotations:
                if ann.id not in before_notes:
                    assert ann.provenance in ("inferred", "illustrative")
            for edge in session.board.edges:
                if edge.id.startswith("x:"):
                    assert edge.provenance in ("inferred", "illustrative")

    run(scenario())


# ------------------------------------------------------------------------------------ CORE-P12
@FAST
@given(
    refs_st,
    st.booleans(),
    st.integers(0, 3),
    st.lists(mock_change_st, max_size=6),
    st.one_of(st.none(), st.just({"card": ["title", "column", "nope"], "column": ["title"]})),
)
def test_prop_core_p12_projection_is_deterministic(refs, include_children, max_depth, changes, props_config) -> None:
    """CORE-P12: projecting the same observation and refs twice gives identical nodes and edges, and does not
    change the observation."""

    async def scenario() -> None:
        _, conn = make_session()
        for change in changes:
            await apply_mock_change(conn, change)
        obs = await conn.observe(Scope(level="full"))
        frozen = obs.model_dump_json()
        first = project(obs, refs, include_children, props_config, max_depth)
        second = project(obs, refs, include_children, props_config, max_depth)
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
        assert obs.model_dump_json() == frozen
        ops, missing = first
        by_ref = {e.ref for e in obs.entities}
        assert set(missing) == {r for r in refs if r not in by_ref}
        ids = [op["node"]["id"] for op in ops if op["op"] == "add_node"]
        assert len(ids) == len(set(ids))
        # a second observation of the unchanged state projects identically as well
        again = project(await conn.observe(Scope(level="full")), refs, include_children, props_config, max_depth)
        assert [o for o in again[0] if o["op"] != "add_node"] == [o for o in ops if o["op"] != "add_node"]
        assert [o["node"]["id"] for o in again[0] if o["op"] == "add_node"] == ids

    run(scenario())
