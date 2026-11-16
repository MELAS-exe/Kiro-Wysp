"""Event (notification) payloads sent by adapters, and request params for Core to adapter calls."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .actions import ActionCall, Origin, Predicate
from .observation import Ref, Scope


class StateChanged(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_version: int = Field(ge=0)
    changed: list[Ref] = Field(default_factory=list)
    origin: Origin = "unknown"


class SelectionChanged(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: list[Ref] = Field(default_factory=list)


class UserAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    target: Ref | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)
    origin: Origin = "user"


class Navigation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    title: str = ""


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_version: int | None = None


class ObserveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope = Field(default_factory=Scope)


class ExecuteParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call: ActionCall


class UndoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str


class HighlightParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: Ref
    style: Literal["pulse", "outline"] = "pulse"
    # 0 (contract 1.1): the highlight stays until cleared, replaced, dismissed by the user or the adapter disconnects.
    duration_ms: int = Field(default=2500, ge=0, le=10000)


class HighlightDismissed(BaseModel):
    """The user interacted with a persistent highlight and the adapter removed it (contract 1.1)."""

    model_config = ConfigDict(extra="forbid")
    ref: Ref
    reason: Literal["user"] = "user"


class VerifyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: Predicate
