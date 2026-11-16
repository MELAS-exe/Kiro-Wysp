"""CON-P1 schema round trip [adapter-contract 2.1]: contract model -> JSON -> exported JSON Schema -> model.

For randomly generated instances of the contract models, serialising (by alias, JSON mode, through a real
`json.dumps`/`json.loads`), validating against the schema written in `schemas/`, and parsing back gives an equal
instance. The schemas on disk are also checked against what the models export today.
"""

from __future__ import annotations

import json
from datetime import UTC, timedelta, timezone
from typing import Any

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter
from wysp_core.contract import (
    ActionCall,
    ActionResult,
    ActionSpec,
    Context,
    Entity,
    Evidence,
    HelloParams,
    HelloResult,
    HighlightDismissed,
    HighlightParams,
    Manifest,
    Navigation,
    Observation,
    Predicate,
    PredicateOutcome,
    RpcRequest,
    RpcResponse,
    Scope,
    SelectionChanged,
    StateChanged,
    UndoParams,
    UserAction,
    VerifyParams,
)
from wysp_core.contract.events import ExecuteParams, ObserveParams
from wysp_core.contract.export import build_schemas, find_repo_root
from wysp_core.contract.ui import inbound_adapter

FAST = settings(max_examples=50, deadline=None)
SCHEMAS_DIR = find_repo_root() / "schemas"

# ------------------------------------------------------------------------------------ strategies
text = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=12)
word = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=8)
ref = st.builds(lambda scheme, rest: f"{scheme}://{rest}", st.sampled_from(["mock", "blender", "web", "x1"]), word)
refs = st.lists(ref, max_size=4)
json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-(2**53), 2**53),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    text,
)
json_value = st.recursive(
    json_scalar,
    lambda inner: st.one_of(st.lists(inner, max_size=3), st.dictionaries(word, inner, max_size=3)),
    max_leaves=8,
)
json_obj = st.dictionaries(word, json_value, max_size=3)
state_version = st.integers(0, 10**6)
origin = st.sampled_from(["user", "wysp", "unknown"])
localized = st.one_of(text, st.dictionaries(st.sampled_from(["en", "fr", "de"]), text, min_size=1, max_size=3))

compare = st.builds(
    lambda r, path, op, value: {"ref": r, "path": path, "op": op, "value": value},
    st.none() | ref,
    word,
    st.sampled_from(
        ["eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "exists", "not_exists", "matches", "len_eq", "len_gte"]
    ),
    json_value,
)
predicate_json = st.recursive(
    compare,
    lambda inner: st.one_of(
        st.lists(inner, min_size=1, max_size=3).map(lambda xs: {"all": xs}),
        st.lists(inner, min_size=1, max_size=3).map(lambda xs: {"any": xs}),
        inner.map(lambda x: {"not": x}),
    ),
    max_leaves=6,
)
predicate = predicate_json.map(TypeAdapter(Predicate).validate_python)

entity = st.builds(
    Entity,
    ref=ref,
    kind=word,
    label=text,
    parent=st.none() | ref,
    props=json_obj,
    confidence=st.floats(0.0, 1.0),
)
scope = st.builds(
    Scope,
    level=st.sampled_from(["summary", "focus", "full"]),
    root=st.none() | ref,
    depth=st.none() | st.integers(0, 8),
)
observation = st.builds(
    lambda oid, sv, dt, sc, ents, links, focus, trunc, counts: Observation.model_validate(
        {
            "observation_id": oid,
            "state_version": sv,
            "captured_at": dt,
            "scope": sc,
            "entities": ents,
            "links": [{"from": a, "to": b, "kind": k} for a, b, k in links],
            "focus": focus,
            "truncated": trunc,
            "counts": counts,
        }
    ),
    word,
    state_version,
    st.datetimes(timezones=st.just(UTC) | st.integers(-12, 14).map(lambda h: timezone(timedelta(hours=h)))),
    scope,
    st.lists(entity, max_size=4),
    st.lists(st.tuples(ref, ref, word), max_size=3),
    refs,
    st.booleans(),
    st.dictionaries(word, st.integers(0, 1000), max_size=3),
)
context = st.builds(Context, summary=text, mode=st.none() | word, focus=refs, facts=json_obj)
action_spec = st.builds(
    lambda i, title, desc, schema, risk, pre, post, guide: ActionSpec.model_validate(
        {
            "id": i,
            "title": title,
            "description": desc,
            "params_schema": schema,
            "risk": risk,
            "reversible": risk == "reversible",
            "preconditions": pre,
            "postconditions": post,
            "guide": guide,
        }
    ),
    word,
    localized,
    text,
    json_obj,
    st.sampled_from(["read_only", "ui_state", "reversible", "irreversible"]),
    st.lists(predicate_json, max_size=2),
    st.lists(predicate_json, max_size=2),
    st.none()
    | st.builds(
        lambda steps: {"ui_path": steps},
        st.lists(st.builds(lambda t, g: {"text": t, "target": g}, localized, st.none() | text), max_size=3),
    ),
)
action_call = st.builds(ActionCall, action_id=word, params=json_obj, request_id=word, dry_run=st.booleans())
action_result = st.builds(
    ActionResult,
    status=st.sampled_from(["ok", "failed"]),
    state_version=state_version,
    changed=refs,
    undo_token=st.none() | word,
    message=st.none() | text,
    preview=json_value,
)
outcome = st.recursive(
    st.builds(
        PredicateOutcome,
        ok=st.booleans(),
        path=st.none() | word,
        op=st.none() | word,
        actual=json_value,
        expected=json_value,
    ),
    lambda inner: st.builds(
        PredicateOutcome,
        ok=st.booleans(),
        op=st.sampled_from(["all", "any", "not"]),
        children=st.lists(inner, max_size=3),
    ),
    max_leaves=5,
)
evidence = st.builds(
    Evidence,
    id=word,
    type=st.sampled_from(["verified", "answered", "declared"]),
    source=st.sampled_from(["core", "adapter", "learner"]),
    exercise_id=st.none() | word,
    skills=st.lists(word, max_size=3),
    outcomes=st.lists(outcome, max_size=2),
    observation_id=st.none() | word,
    state_version=st.none() | state_version,
    created_at=text,
    hints_used=st.integers(0, 5),
)
CAPS = [
    "observe", "context", "actions", "execute", "undo", "highlight",
    "events.state", "events.selection", "events.user_action", "events.navigation", "verify.native",
]  # fmt: skip
manifest = st.builds(
    lambda aid, name, ver, cv, level, scheme, caps, kinds, vol, loc, pid: Manifest.model_validate(
        {
            "adapter_id": aid,
            "app": {"name": name, "version": ver},
            "contract_version": cv,
            "integration_level": level,
            "ref_scheme": scheme,
            "capabilities": caps,
            "entity_kinds": [{"kind": k, "label": lb, "description": d} for k, lb, d in kinds],
            "volatile_props": vol,
            "locales": loc,
            "profile_id": pid,
        }
    ),
    word,
    text,
    text,
    st.sampled_from(["1.0.0", "1.1.0"]),
    st.sampled_from(["native", "interface", "visual"]),
    word,
    st.lists(st.sampled_from(CAPS), max_size=5, unique=True),
    st.lists(st.tuples(word, text, st.none() | text), max_size=3),
    st.lists(word, max_size=3),
    st.lists(st.sampled_from(["en", "fr", "de"]), min_size=1, max_size=3, unique=True),
    st.none() | word,
)
rpc_request = st.builds(
    RpcRequest,
    id=st.none() | st.integers(0, 10**6) | word,
    method=word,
    params=st.none() | json_obj,
)
rpc_response = st.one_of(
    st.builds(RpcResponse, id=st.none() | st.integers(0, 10**6) | word, result=json_value),
    st.builds(
        lambda i, c, m, d: RpcResponse.model_validate({"id": i, "error": {"code": c, "message": m, "data": d}}),
        st.none() | st.integers(0, 10**6) | word,
        st.integers(-32800, -32000),
        text,
        json_value,
    ),
)
ui_inbound_json = st.one_of(
    st.builds(
        lambda t, s: {"type": "user.message", "text": "x" + t, "source": s}, text, st.sampled_from(["typed", "voice"])
    ),
    st.just({"type": "user.interrupt"}),
    st.just({"type": "user.continue"}),
    st.builds(
        lambda r, d, v: {"type": "permission.respond", "request_id": r, "decision": d, "via": v},
        word,
        st.sampled_from(["approve", "deny", "grant_lesson"]),
        st.sampled_from(["click", "voice"]),
    ),
    st.builds(lambda n: {"type": "board.select", "node_id": n}, word),
    st.builds(lambda n: {"type": "board.ask_why", "node_id": n}, word),
    st.builds(lambda s, p: {"type": "narration.progress", "segment_id": s, "played": p}, word, st.booleans()),
    st.builds(lambda s, i: {"type": "narration.cue", "segment_id": s, "index": i}, word, st.integers(0, 50)),
    st.builds(lambda a: {"type": "adapter.activate", "adapter_id": a}, word),
    st.just({"type": "board.snapshot_request"}),
    st.just({"type": "undo.last"}),
    st.builds(
        lambda lang, log: {"type": "settings.update", "lang": lang, "logging": log},
        st.none() | st.sampled_from(["en", "fr"]),
        st.none() | st.sampled_from(["off", "basic", "full"]),
    ),
    st.just({"type": "explore.start"}),
    st.just({"type": "explore.stop"}),
)

# schema name -> (type adapter used to dump and parse, strategy of instances)
CASES: dict[str, tuple[TypeAdapter[Any], st.SearchStrategy[Any]]] = {
    "rpc-request": (TypeAdapter(RpcRequest), rpc_request),
    "rpc-response": (TypeAdapter(RpcResponse), rpc_response),
    "manifest": (TypeAdapter(Manifest), manifest),
    "hello-params": (TypeAdapter(HelloParams), st.builds(HelloParams, manifest=manifest, token=word)),
    "hello-result": (
        TypeAdapter(HelloResult),
        st.builds(
            HelloResult,
            session_id=word,
            contract_version=st.sampled_from(["1.0.0", "1.1.0"]),
            core_version=word,
            heartbeat_interval_s=st.floats(0.5, 120, allow_nan=False),
        ),
    ),
    "scope": (TypeAdapter(Scope), scope),
    "entity": (TypeAdapter(Entity), entity),
    "observation": (TypeAdapter(Observation), observation),
    "context": (TypeAdapter(Context), context),
    "predicate": (TypeAdapter(Predicate), predicate),
    "predicate-outcome": (TypeAdapter(PredicateOutcome), outcome),
    "action-spec": (TypeAdapter(ActionSpec), action_spec),
    "action-call": (TypeAdapter(ActionCall), action_call),
    "action-result": (TypeAdapter(ActionResult), action_result),
    "evidence": (TypeAdapter(Evidence), evidence),
    "event-state-changed": (
        TypeAdapter(StateChanged),
        st.builds(StateChanged, state_version=state_version, changed=refs, origin=origin),
    ),
    "event-selection-changed": (TypeAdapter(SelectionChanged), st.builds(SelectionChanged, focus=refs)),
    "event-user-action": (
        TypeAdapter(UserAction),
        st.builds(UserAction, kind=word, target=st.none() | ref, details=json_obj, origin=origin),
    ),
    "event-navigation": (TypeAdapter(Navigation), st.builds(Navigation, url=text, title=text)),
    "event-highlight-dismissed": (TypeAdapter(HighlightDismissed), st.builds(HighlightDismissed, ref=ref)),
    "params-observe": (TypeAdapter(ObserveParams), st.builds(ObserveParams, scope=scope)),
    "params-execute": (TypeAdapter(ExecuteParams), st.builds(ExecuteParams, call=action_call)),
    "params-undo": (TypeAdapter(UndoParams), st.builds(UndoParams, token=word)),
    "params-highlight": (
        TypeAdapter(HighlightParams),
        st.builds(
            HighlightParams, ref=ref, style=st.sampled_from(["pulse", "outline"]), duration_ms=st.integers(0, 10000)
        ),
    ),
    "params-verify": (TypeAdapter(VerifyParams), st.builds(VerifyParams, goal=predicate)),
    "ui-inbound": (inbound_adapter, ui_inbound_json.map(inbound_adapter.validate_python)),
}


# ------------------------------------------------------------------------------------------- tests
def test_cases_cover_every_exported_schema() -> None:
    assert set(CASES) == set(build_schemas())


def test_schemas_on_disk_match_the_models() -> None:
    """The files in schemas/ (what the round trip validates against) are what the models export today."""
    for name, schema in build_schemas().items():
        on_disk = json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert on_disk == json.loads(json.dumps(schema)), f"schemas/{name}.schema.json is stale"


@pytest.mark.parametrize("name", sorted(CASES))
def test_prop_con_p1_schema_round_trip(name: str) -> None:
    """CON-P1: model -> JSON text -> JSON Schema validation -> model gives an equal instance."""
    adapter, strategy = CASES[name]
    schema = json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    @FAST
    @given(strategy)
    def check(instance: Any) -> None:
        payload = json.loads(json.dumps(adapter.dump_python(instance, mode="json", by_alias=True)))
        validator.validate(payload)
        assert adapter.validate_python(payload) == instance

    check()
