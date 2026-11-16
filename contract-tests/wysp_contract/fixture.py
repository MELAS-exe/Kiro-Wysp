"""The `contract.fixture.yaml` of a tutor: model, loader and validation [adapter-contract 9].

    tutor           id of the tutor
    launch          how the kit starts the adapter: command | playwright | manual | in_process
    expect          entity kinds the manifest declares, minimum entities, the exact action catalog
    safe_calls      actions the kit executes (reversible ones are undone); postconditions are checked
    dry_run_calls   executed with dry_run=true; the state digest must not change
    invalid_calls   executed with bad input; the error code must match and the state digest must not change
    skip            checks the tutor cannot run, with the reason (`highlight`, `action:<id>`, ...)

The JSON Schema of this model is `fixture.schema.json` next to this file (a test keeps it in sync with the model;\nregenerate it with `python -m wysp_contract.fixture`). It lives here, not in `schemas/`, which is generated from the\nCore\'s contract models only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

LaunchKind = Literal["command", "playwright", "manual", "in_process"]


class Launch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: LaunchKind
    command: list[str] = Field(default_factory=list, description="argv; {placeholders} are filled in by the kit")
    env: dict[str, str] = Field(default_factory=dict)
    connect_timeout_s: float = Field(default=60, gt=0)
    instructions: str | None = Field(default=None, description="kind manual: what the person must do")
    adapter: str | None = Field(default=None, description="kind in_process: 'module:function' starting the adapter")
    faults: list[str] = Field(default_factory=list, description="kind in_process: deliberate faults (kit self-test)")
    allowed_origins: list[str] = Field(default_factory=list, description="extra Origin values the harness accepts")

    @model_validator(mode="after")
    def _kind_needs(self) -> Launch:
        if self.kind in ("command", "playwright") and not self.command:
            raise ValueError(f"launch.kind '{self.kind}' needs a command")
        if self.kind == "manual" and not self.instructions:
            raise ValueError("launch.kind 'manual' needs instructions")
        if self.kind == "in_process" and not self.adapter:
            raise ValueError("launch.kind 'in_process' needs adapter")
        return self


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_kinds: list[str] = Field(default_factory=list)
    min_entities: int = Field(default=1, ge=0)
    actions: list[str] = Field(default_factory=list)


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    expect_error: int | None = None


class Skip(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str
    reason: str


class Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tutor: str
    launch: Launch
    expect: Expect
    safe_calls: list[Call] = Field(default_factory=list)
    dry_run_calls: list[Call] = Field(default_factory=list)
    invalid_calls: list[Call] = Field(default_factory=list)
    skip: list[Skip] = Field(default_factory=list)

    def skipped(self, check: str) -> str | None:
        """The reason when the fixture skips this check, else None."""
        return next((s.reason for s in self.skip if s.check == check), None)


def validate_fixture(path: Path) -> list[str]:
    """Return the problems of a fixture file (empty when it is valid)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"{path}: cannot read ({exc})"]
    if not isinstance(data, dict):
        return [f"{path}: the fixture must be a mapping"]
    problems = [
        f"missing '{key}'" for key in ("tutor", "launch", "expect", "safe_calls", "invalid_calls") if key not in data
    ]
    try:
        fixture = Fixture.model_validate(data)
    except ValidationError as exc:
        problems += [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors() if e["type"] != "missing"
        ]
        return problems
    expected = set(fixture.expect.actions)
    for section in ("safe_calls", "dry_run_calls"):
        for call in getattr(fixture, section):
            if expected and call.action_id not in expected:
                problems.append(f"{section}: '{call.action_id}' is not in expect.actions")
    for call in fixture.invalid_calls:
        if call.expect_error is None:
            problems.append(f"invalid_calls: '{call.action_id}' needs expect_error")
    return problems


def load_fixture(path: Path) -> Fixture:
    return Fixture.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


if __name__ == "__main__":  # regenerate fixture.schema.json
    import json

    out = Path(__file__).with_name("fixture.schema.json")
    out.write_text(
        json.dumps(Fixture.model_json_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
