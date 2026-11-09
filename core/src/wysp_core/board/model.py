"""The Visual Model: a structured board (nodes, edges, steps, annotations), never an image."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Provenance = Literal["observed", "inferred", "illustrative"]
Layout = Literal["stack", "tree", "graph", "sequence"]
StepStatus = Literal["pending", "active", "done", "failed"]

MAX_NODES = 60


class BoardNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ref: str | None = None
    kind: str
    label: str
    provenance: Provenance
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    props_view: list[list[str]] = Field(default_factory=list)  # [[key, value], ...] up to 6
    group: str | None = None
    badges: list[str] = Field(default_factory=list)
    order: int | None = None  # position in an ordered list (e.g. a stack), when meaningful


class BoardEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source: str
    target: str
    kind: str
    label: str | None = None
    provenance: Provenance = "observed"


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    index: int
    text: str
    status: StepStatus = "pending"
    target: str | None = None  # node id


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    target: str  # node id
    text: str
    provenance: Provenance = "inferred"


class Board(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 0
    layout: Layout = "graph"
    focus: list[str] = Field(default_factory=list)  # node ids
    nodes: list[BoardNode] = Field(default_factory=list)
    edges: list[BoardEdge] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    stale: bool = False

    def node(self, node_id: str) -> BoardNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)


class BoardPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int
    version: int
    ops: list[dict]
