"""Error codes of the adapter contract (JSON-RPC standard codes plus Wysp codes)."""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class ErrorCode(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    NOT_SUPPORTED = -32010
    ACTION_NOT_FOUND = -32011
    TARGET_NOT_FOUND = -32012
    PRECONDITION_FAILED = -32013
    EXECUTION_FAILED = -32014
    UNDO_UNAVAILABLE = -32015
    TIMEOUT = -32016
    BUSY = -32017
    INCOMPATIBLE_VERSION = -32018
    UNAUTHORIZED = -32019


class WyspError(Exception):
    """An error that maps to a JSON-RPC error object. Never carries a stack trace."""

    def __init__(self, code: int | ErrorCode, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = int(code)
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out
