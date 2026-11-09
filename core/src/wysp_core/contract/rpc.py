"""JSON-RPC 2.0 envelope models and the contract version."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue

CONTRACT_VERSION = "1.0.0"

# Methods, by direction. "A" = adapter to Core, "C" = Core to adapter.
METHOD_HELLO = "wysp.hello"  # A -> C request
METHOD_HEARTBEAT = "wysp.heartbeat"  # A -> C notification
METHOD_BYE = "wysp.bye"  # A -> C notification
METHOD_OBSERVE = "adapter.observe"  # C -> A request
METHOD_GET_CONTEXT = "adapter.get_context"
METHOD_GET_ACTIONS = "adapter.get_actions"
METHOD_EXECUTE = "adapter.execute"
METHOD_UNDO = "adapter.undo"
METHOD_HIGHLIGHT = "adapter.highlight"
METHOD_VERIFY = "adapter.verify"
EVENT_STATE_CHANGED = "event.state_changed"  # A -> C notifications
EVENT_SELECTION_CHANGED = "event.selection_changed"
EVENT_USER_ACTION = "event.user_action"
EVENT_NAVIGATION = "event.navigation"

# Time budgets in seconds for Core -> adapter requests.
BUDGETS_S: dict[str, float] = {
    METHOD_OBSERVE: 1.0,
    METHOD_GET_CONTEXT: 0.5,
    METHOD_GET_ACTIONS: 0.5,
    METHOD_EXECUTE: 5.0,
    METHOD_UNDO: 5.0,
    METHOD_HIGHLIGHT: 0.5,
    METHOD_VERIFY: 2.0,
}

# Capability required for each Core -> adapter method.
METHOD_CAPABILITY: dict[str, str] = {
    METHOD_OBSERVE: "observe",
    METHOD_GET_CONTEXT: "context",
    METHOD_GET_ACTIONS: "actions",
    METHOD_EXECUTE: "execute",
    METHOD_UNDO: "undo",
    METHOD_HIGHLIGHT: "highlight",
    METHOD_VERIFY: "verify.native",
}


class RpcError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: int
    message: str
    data: JsonValue | None = None


class RpcRequest(BaseModel):
    """A request (has an id) or a notification (no id)."""

    model_config = ConfigDict(extra="forbid")
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, JsonValue] | None = None

    @property
    def is_notification(self) -> bool:
        return self.id is None


class RpcResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None
    result: JsonValue | None = None
    error: RpcError | None = None


def ok_response(request_id: int | str | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: int | str | None, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def split_version(version: str) -> tuple[int, int, int]:
    major, minor, patch = (version.split(".") + ["0", "0"])[:3]
    return int(major), int(minor), int(patch)
