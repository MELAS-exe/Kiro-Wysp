"""A connected adapter: typed calls with budgets, pending-request tracking and capability checks."""

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any, Protocol

from ..contract import (
    ActionCall,
    ActionResult,
    ActionSpec,
    Context,
    ErrorCode,
    Manifest,
    Observation,
    Scope,
    WyspError,
)
from ..contract.rpc import (
    BUDGETS_S,
    METHOD_CAPABILITY,
    METHOD_EXECUTE,
    METHOD_GET_ACTIONS,
    METHOD_GET_CONTEXT,
    METHOD_HIGHLIGHT,
    METHOD_OBSERVE,
    METHOD_UNDO,
)

# Extra time on top of the contract budgets, for the network hop and the host's dispatch pump.
SLACK_S = 1.0


class Transport(Protocol):
    async def send_json(self, message: dict[str, Any]) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


class AdapterConnection:
    def __init__(self, transport: Transport, manifest: Manifest, session_id: str, telemetry=None) -> None:
        self.tm = telemetry
        self.transport = transport
        self.manifest = manifest
        self.session_id = session_id
        self.connected = True
        self.last_seen = time.monotonic()
        self.state_version = 0
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._actions_cache: list[ActionSpec] | None = None

    @property
    def adapter_id(self) -> str:
        return self.manifest.adapter_id

    # ------------------------------------------------------------------------ plumbing
    def resolve(self, message: dict[str, Any]) -> None:
        """Called by the server loop for every response from the adapter."""
        fut = self._pending.pop(message.get("id"), None)  # type: ignore[arg-type]
        if fut is None or fut.done():
            return
        if "error" in message and message["error"] is not None:
            err = message["error"]
            fut.set_exception(
                WyspError(err.get("code", ErrorCode.INTERNAL_ERROR), err.get("message", ""), err.get("data"))
            )
        else:
            fut.set_result(message.get("result"))

    def fail_all(self, reason: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(WyspError(ErrorCode.TIMEOUT, reason))
        self._pending.clear()
        self.connected = False

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        capability = METHOD_CAPABILITY.get(method)
        if capability and not self.manifest.has(capability):
            raise WyspError(ErrorCode.NOT_SUPPORTED, f"adapter '{self.adapter_id}' does not declare '{capability}'")
        if not self.connected:
            raise WyspError(ErrorCode.TIMEOUT, f"adapter '{self.adapter_id}' is disconnected")
        request_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        budget = (timeout if timeout is not None else BUDGETS_S.get(method, 5.0)) + SLACK_S
        started = time.monotonic()
        code: int | None = None
        try:
            await self.transport.send_json(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
            )
            return await asyncio.wait_for(fut, budget)
        except TimeoutError as exc:
            code = int(ErrorCode.TIMEOUT)
            raise WyspError(ErrorCode.TIMEOUT, f"{method} exceeded {budget:.1f}s") from exc
        except WyspError as exc:
            code = exc.code
            raise
        finally:
            self._pending.pop(request_id, None)
            if self.tm is not None:
                self.tm.emit(
                    "adapter.call",
                    full={"params": params},
                    method=method,
                    adapter=self.adapter_id,
                    duration_ms=round((time.monotonic() - started) * 1000, 1),
                    ok=code is None,
                    code=code,
                    budget_s=budget,
                )

    # --------------------------------------------------------------------- typed calls
    async def observe(self, scope: Scope | None = None) -> Observation:
        raw = await self.call(METHOD_OBSERVE, {"scope": (scope or Scope()).model_dump(mode="json", exclude_none=True)})
        obs = Observation.model_validate(raw)
        self.state_version = max(self.state_version, obs.state_version)
        return obs

    async def get_context(self) -> Context:
        return Context.model_validate(await self.call(METHOD_GET_CONTEXT))

    async def get_actions(self, refresh: bool = False) -> list[ActionSpec]:
        if self._actions_cache is None or refresh:
            raw = await self.call(METHOD_GET_ACTIONS)
            self._actions_cache = [ActionSpec.model_validate(a) for a in raw]
        return self._actions_cache

    async def execute(self, call: ActionCall) -> ActionResult:
        raw = await self.call(METHOD_EXECUTE, {"call": call.model_dump(mode="json")})
        return ActionResult.model_validate(raw)

    async def undo(self, token: str) -> ActionResult:
        return ActionResult.model_validate(await self.call(METHOD_UNDO, {"token": token}))

    async def highlight(self, ref: str, style: str = "pulse", duration_ms: int = 2500) -> None:
        await self.call(METHOD_HIGHLIGHT, {"ref": ref, "style": style, "duration_ms": duration_ms})
