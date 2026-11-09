"""Observation model: an application-independent entity graph."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

Ref = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9+.-]*://.+$", max_length=512)]

MAX_ENTITIES = 500
MAX_OBSERVATION_BYTES = 256 * 1024
MAX_CONTEXT_BYTES = 8 * 1024


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["summary", "focus", "full"] = "focus"
    root: Ref | None = None
    depth: int | None = Field(default=None, ge=0, le=8)


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: Ref
    kind: str
    label: str
    parent: Ref | None = None
    props: dict[str, JsonValue] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: Ref = Field(alias="from")
    to: Ref
    kind: str


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    observation_id: str
    state_version: int = Field(ge=0)
    captured_at: datetime
    scope: Scope = Field(default_factory=Scope)
    entities: list[Entity] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    focus: list[Ref] = Field(default_factory=list)
    truncated: bool = False
    counts: dict[str, int] = Field(default_factory=dict)

    def entity(self, ref: str) -> Entity | None:
        for e in self.entities:
            if e.ref == ref:
                return e
        return None

    def children_of(self, ref: str) -> list[Entity]:
        return [e for e in self.entities if e.parent == ref]


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    mode: str | None = None
    focus: list[Ref] = Field(default_factory=list)
    facts: dict[str, JsonValue] = Field(default_factory=dict)


def check_observation(obs: Observation, declared_kinds: set[str] | None = None) -> list[str]:
    """Return referential-integrity problems (property CON-P2). Empty list means valid."""
    problems: list[str] = []
    refs = [e.ref for e in obs.entities]
    seen: set[str] = set()
    for r in refs:
        if r in seen:
            problems.append(f"duplicate ref {r}")
        seen.add(r)
    for e in obs.entities:
        if e.parent is not None and e.parent not in seen:
            problems.append(f"parent {e.parent} of {e.ref} is not in the observation")
        if declared_kinds is not None and e.kind not in declared_kinds:
            problems.append(f"kind {e.kind!r} of {e.ref} is not declared in the manifest")
    for link in obs.links:
        for end in (link.from_, link.to):
            if end not in seen:
                problems.append(f"link endpoint {end} is not in the observation")
    for f in obs.focus:
        if f not in seen:
            problems.append(f"focus ref {f} is not in the observation")
    if len(obs.entities) > MAX_ENTITIES:
        problems.append(f"{len(obs.entities)} entities exceed the limit of {MAX_ENTITIES}")
    return problems
