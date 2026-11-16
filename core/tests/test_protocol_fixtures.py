"""Golden protocol fixtures [adapter-contract 5]: the same files are checked here with the models and the JSON
Schemas, and in `sdk/ts/tests/fixtures.test.ts` with ajv. A fixture is `{"schema": <name>, "payload": ...}`."""

from __future__ import annotations

import json

import jsonschema
import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError
from wysp_core.contract.export import _models, find_repo_root

ROOT = find_repo_root()
FIXTURES = ROOT / "contract-tests" / "fixtures" / "protocol"
SCHEMAS = ROOT / "schemas"


def _adapter(name: str) -> TypeAdapter:
    model = _models()[name]
    return model if isinstance(model, TypeAdapter) else TypeAdapter(model)  # type: ignore[arg-type]


def _load(kind: str) -> list[tuple[str, dict]]:
    return [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in sorted((FIXTURES / kind).glob("*.json"))]


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_there_are_fixtures_for_every_message_family() -> None:
    names = {fx["schema"] for _, fx in _load("valid")}
    for needed in (
        "hello-params", "hello-result", "observation", "action-spec", "action-call", "action-result",
        "event-state-changed", "event-user-action", "event-highlight-dismissed", "rpc-request", "rpc-response",
    ):  # fmt: skip
        assert needed in names, needed
    assert len(_load("invalid")) >= 15
    assert any("error" in fx["payload"] for _, fx in _load("valid") if fx["schema"] == "rpc-response")


@pytest.mark.parametrize(("name", "fx"), _load("valid"), ids=[n for n, _ in _load("valid")])
def test_valid_fixture_passes_the_schema_and_the_model_and_round_trips(name: str, fx: dict) -> None:
    payload = fx["payload"]
    jsonschema.Draft202012Validator(_schema(fx["schema"])).validate(payload)
    adapter = _adapter(fx["schema"])
    parsed = adapter.validate_python(payload)
    again = adapter.dump_python(parsed, mode="json", by_alias=True)
    assert adapter.validate_python(again) == parsed
    if isinstance(parsed, BaseModel):
        assert parsed == type(parsed).model_validate(json.loads(json.dumps(again)))


@pytest.mark.parametrize(("name", "fx"), _load("invalid"), ids=[n for n, _ in _load("invalid")])
def test_invalid_fixture_is_rejected_by_the_schema_and_by_the_model(name: str, fx: dict) -> None:
    validator = jsonschema.Draft202012Validator(_schema(fx["schema"]))
    assert not validator.is_valid(fx["payload"]), "the schema accepted an invalid message"
    with pytest.raises(ValidationError):
        _adapter(fx["schema"]).validate_python(fx["payload"])
