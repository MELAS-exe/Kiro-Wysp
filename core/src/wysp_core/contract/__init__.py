"""The adapter contract: Pydantic models are the single source of truth.

Everything the Core, the SDKs and the Contract Test Kit share lives here. This package must not
import anything else from wysp_core.
"""

from .actions import (
    ActionCall,
    ActionResult,
    ActionSpec,
    Evidence,
    Guide,
    GuideStep,
    Origin,
    Predicate,
    PredicateOutcome,
    Risk,
)
from .digest import canonical_json, digest
from .errors import ErrorCode, WyspError
from .events import (
    ExecuteParams,
    Heartbeat,
    HighlightDismissed,
    HighlightParams,
    Navigation,
    ObserveParams,
    SelectionChanged,
    StateChanged,
    UndoParams,
    UserAction,
    VerifyParams,
)
from .manifest import AppInfo, Capability, EntityKind, HelloParams, HelloResult, Manifest
from .observation import Context, Entity, Link, Observation, Ref, Scope, check_observation
from .rpc import CONTRACT_VERSION, RpcError, RpcRequest, RpcResponse

__all__ = [
    "CONTRACT_VERSION",
    "ActionCall",
    "ActionResult",
    "ActionSpec",
    "AppInfo",
    "Capability",
    "Context",
    "Entity",
    "EntityKind",
    "ErrorCode",
    "Evidence",
    "ExecuteParams",
    "Guide",
    "GuideStep",
    "Heartbeat",
    "HelloParams",
    "HelloResult",
    "HighlightDismissed",
    "HighlightParams",
    "Link",
    "Manifest",
    "Navigation",
    "ObserveParams",
    "Observation",
    "Origin",
    "Predicate",
    "PredicateOutcome",
    "Ref",
    "Risk",
    "RpcError",
    "RpcRequest",
    "RpcResponse",
    "Scope",
    "SelectionChanged",
    "StateChanged",
    "UndoParams",
    "UserAction",
    "VerifyParams",
    "WyspError",
    "canonical_json",
    "check_observation",
    "digest",
]
