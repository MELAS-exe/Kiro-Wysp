"""Action catalog, calls and results, and the predicate model."""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .observation import Ref

Risk = Literal["read_only", "ui_state", "reversible", "irreversible"]
Op = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "exists", "not_exists", "matches",
    "len_eq", "len_gte",
]  # fmt: skip
Origin = Literal["user", "wysp", "unknown"]

LocalizedText = Union[str, dict[str, str]]  # noqa: UP007 - a plain string or a {locale: text} map


# ----------------------------------------------------------------------------- predicates
class Compare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str | None = None
    path: str
    op: Op
    value: JsonValue = None


class AllOf(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    all_: list[Predicate] = Field(alias="all", min_length=1)


class AnyOf(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    any_: list[Predicate] = Field(alias="any", min_length=1)


class Not(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    not_: Predicate = Field(alias="not")


Predicate = Union[Compare, AllOf, AnyOf, Not]  # noqa: UP007
for _m in (AllOf, AnyOf, Not):
    _m.model_rebuild()


class PredicateOutcome(BaseModel):
    """Result of evaluating a predicate: the raw material of an Evidence record."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    path: str | None = None
    op: str | None = None
    actual: JsonValue = None
    expected: JsonValue = None
    children: list[PredicateOutcome] = Field(default_factory=list)


# --------------------------------------------------------------------------------- actions
class GuideStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: LocalizedText
    target: Ref | None = None


class Guide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ui_path: list[GuideStep] = Field(default_factory=list)


class ActionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: LocalizedText
    description: str
    params_schema: dict[str, JsonValue]
    risk: Risk
    reversible: bool
    preconditions: list[Predicate] = Field(default_factory=list)
    postconditions: list[Predicate] = Field(default_factory=list)
    guide: Guide | None = None

    def validate_consistency(self) -> list[str]:
        problems = []
        if self.risk == "reversible" and not self.reversible:
            problems.append(f"{self.id}: risk 'reversible' requires reversible=true")
        if self.risk == "irreversible" and self.reversible:
            problems.append(f"{self.id}: risk 'irreversible' requires reversible=false")
        return problems


class ActionCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str
    params: dict[str, JsonValue] = Field(default_factory=dict)
    request_id: str
    dry_run: bool = False


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "failed"]
    state_version: int = Field(ge=0)
    changed: list[Ref] = Field(default_factory=list)
    undo_token: str | None = None
    message: str | None = None
    preview: JsonValue = None


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["verified", "answered", "declared"]
    source: Literal["core", "adapter", "learner"] = "core"
    exercise_id: str | None = None
    skills: list[str] = Field(default_factory=list)
    outcomes: list[PredicateOutcome] = Field(default_factory=list)
    observation_id: str | None = None
    state_version: int | None = None
    created_at: str
    hints_used: int = 0
