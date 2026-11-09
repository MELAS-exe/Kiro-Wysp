"""Contract tests: predicates (CON-P11), digest (CON-P4), schema round trip (CON-P1)."""

from __future__ import annotations

from datetime import UTC, datetime

import jmespath
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter
from wysp_core.contract import Entity, Observation, digest
from wysp_core.contract.actions import ActionSpec, Predicate
from wysp_core.contract.export import build_schemas
from wysp_core.contract.predicates import PredicateError, evaluate, parse, substitute


def make_obs(entities: list[Entity], focus: list[str] | None = None) -> Observation:
    return Observation(
        observation_id="o-1",
        state_version=1,
        captured_at=datetime(2026, 11, 9, tzinfo=UTC),
        entities=entities,
        focus=focus or [],
    )


def blender_obs(segments: int = 3) -> Observation:
    return make_obs(
        [
            Entity(ref="blender://object/Candle", kind="object", label="Candle", props={"type": "MESH"}),
            Entity(
                ref="blender://object/Candle/modifier/Bevel",
                kind="modifier",
                label="Bevel",
                parent="blender://object/Candle",
                props={"type": "BEVEL", "segments": segments, "width": 0.1},
            ),
        ]
    )


POST = {
    "all": [
        {
            "path": "entities[?kind=='modifier' && parent=='${params.target}' && props.type=='${params.type}'] | length(@)",
            "op": "gte",
            "value": 1,
        },
        {
            "ref": "${params.target}/modifier/Bevel",
            "path": "props.segments",
            "op": "eq",
            "value": "${params.segments}",
        },
    ]
}


def test_substitute_and_evaluate_postcondition():
    pred = substitute(POST, {"target": "blender://object/Candle", "type": "BEVEL", "segments": 3})
    out = evaluate(pred, blender_obs(3))
    assert out.ok
    assert [c.actual for c in out.children] == [1, 3]
    assert not evaluate(pred, blender_obs(2)).ok


def test_dynamic_key_lookup_with_get():
    pred = substitute({"ref": "${params.t}", "path": "get(props, '${params.k}')", "op": "eq", "value": "${params.v}"},
                      {"t": "blender://object/Candle/modifier/Bevel", "k": "segments", "v": 3})  # fmt: skip
    assert evaluate(pred, blender_obs(3)).ok
    assert not evaluate(pred, blender_obs(2)).ok
    missing = substitute({"ref": "${params.t}", "path": "get(props, '${params.k}')", "op": "not_exists"},
                         {"t": "blender://object/Candle/modifier/Bevel", "k": "nope"})  # fmt: skip
    assert evaluate(missing, blender_obs()).ok


def test_missing_entity_semantics():
    obs = blender_obs()
    assert evaluate({"ref": "blender://object/Nope", "path": "label", "op": "not_exists"}, obs).ok
    assert not evaluate({"ref": "blender://object/Nope", "path": "label", "op": "exists"}, obs).ok
    assert not evaluate({"ref": "blender://object/Nope", "path": "label", "op": "eq", "value": "x"}, obs).ok


@pytest.mark.parametrize(
    "path",
    ["entities[?kind=='${params.x}']", "entities[?kind==${params.x}]", "${params.x}"],
)
def test_placeholder_positions(path: str):
    # Only placeholders inside a single-quoted literal are allowed. Outside: rejected.
    if path == "entities[?kind=='${params.x}']":
        out = substitute({"path": path, "op": "exists"}, {"x": "a"})
        assert out["path"] == "entities[?kind=='a']"
    else:
        with pytest.raises(PredicateError):
            substitute({"path": path, "op": "exists"}, {"x": "a"})


def test_backslash_values_are_rejected_in_paths():
    with pytest.raises(PredicateError):
        substitute({"path": "a=='${params.x}'", "op": "exists"}, {"x": "a\\b"})


def test_parse_rejects_malformed():
    with pytest.raises(PredicateError):
        parse({"path": "a", "op": "nonsense"})
    with pytest.raises(PredicateError):
        parse({"path": "a[", "op": "exists"})
    assert parse({"not": {"path": "a", "op": "exists"}}) == {"not": {"path": "a", "op": "exists"}}


@settings(max_examples=200, deadline=None)
@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\\"), max_size=40))
def test_prop_con_p11_safe_substitution(value: str):
    """CON-P11: for any parameter string, the substituted path parses and compares equal to it."""
    if any(ord(c) < 32 for c in value):
        with pytest.raises(PredicateError):
            substitute({"path": "props.name=='${params.v}'", "op": "exists"}, {"v": value})
        return
    pred = substitute({"path": "props.name=='${params.v}'", "op": "exists"}, {"v": value})
    expr = jmespath.compile(pred["path"])
    assert expr.search({"props": {"name": value}}) is True
    assert expr.search({"props": {"name": value + "x"}}) is False


def test_prop_digest_invariance():
    """CON-P4: order and volatile props do not change the digest; real props do."""
    a = Entity(ref="x://a", kind="k", label="A", props={"v": 1, "tick": 10})
    b = Entity(ref="x://b", kind="k", label="B", parent="x://a", props={"v": 2.0000000001})
    d1 = digest(make_obs([a, b]), ["tick"])
    d2 = digest(make_obs([b, a.model_copy(update={"props": {"v": 1, "tick": 99}})]), ["tick"])
    assert d1 == d2
    d3 = digest(make_obs([a, b.model_copy(update={"props": {"v": 3}})]), ["tick"])
    assert d1 != d3


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.tuples(st.integers(0, 50), st.dictionaries(st.sampled_from("abcd"), st.integers(-5, 5), max_size=3)),
        min_size=1,
        max_size=8,
        unique_by=lambda t: t[0],
    ),
    st.randoms(use_true_random=False),
)
def test_prop_digest_permutation(rows, rnd):
    ents = [Entity(ref=f"x://e{i}", kind="k", label=str(i), props=p) for i, p in rows]
    shuffled = list(ents)
    rnd.shuffle(shuffled)
    assert digest(make_obs(ents)) == digest(make_obs(shuffled))


def test_prop_con_p1_schema_round_trip():
    """CON-P1: model -> JSON -> schema validation -> model, for the main contract models."""
    import jsonschema

    schemas = build_schemas()
    obs = blender_obs()
    payload = obs.model_dump(mode="json", by_alias=True)
    jsonschema.validate(payload, schemas["observation"])
    assert Observation.model_validate(payload) == obs

    spec = ActionSpec(
        id="add_modifier",
        title={"en": "Add a modifier"},
        description="Add a modifier to an object",
        params_schema={"type": "object"},
        risk="reversible",
        reversible=True,
        postconditions=[TypeAdapter(Predicate).validate_python(POST)],
    )
    spec_json = spec.model_dump(mode="json", by_alias=True)
    jsonschema.validate(spec_json, schemas["action-spec"])
    assert ActionSpec.model_validate(spec_json) == spec


def test_every_schema_is_valid_draft_2020():
    import jsonschema

    for name, schema in build_schemas().items():
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["$id"].endswith(f"{name}.schema.json")
