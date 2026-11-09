"""Adapter manifest and the handshake messages."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Capability = Literal[
    "observe",
    "context",
    "actions",
    "execute",
    "undo",
    "highlight",
    "events.state",
    "events.selection",
    "events.user_action",
    "events.navigation",
    "verify.native",
]
IntegrationLevel = Literal["native", "interface", "visual"]


class AppInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str


class EntityKind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    label: str
    description: str | None = None


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter_id: str
    app: AppInfo
    contract_version: str
    integration_level: IntegrationLevel
    ref_scheme: str
    capabilities: list[Capability]
    entity_kinds: list[EntityKind]
    volatile_props: list[str] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=lambda: ["en"])
    profile_id: str | None = None

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    @property
    def kind_names(self) -> set[str]:
        return {k.kind for k in self.entity_kinds}


class HelloParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: Manifest
    token: str


class HelloResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    contract_version: str
    core_version: str
    heartbeat_interval_s: float = 20.0
