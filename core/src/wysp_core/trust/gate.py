"""The permission gate: decides whether a proposed action may run, and asks the user when needed."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from .audit import AuditLog
from .policy import Decision, decide, grant_allowed, voice_may_approve

REQUEST_TIMEOUT_S = 60.0

Via = Literal["click", "voice", "auto", "grant"]
Publish = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass
class Proposal:
    action_id: str
    title: str
    params: dict[str, Any]
    rationale: str
    risk: str
    reversible: bool
    target_label: str | None = None
    preview: Any = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


@dataclass
class Approval:
    approved: bool
    by: str  # "user", "auto", "grant", "timeout"
    via: str


@dataclass
class Grant:
    scope: str
    action_ids: set[str] | None = None  # None means any reversible action


class PermissionGate:
    def __init__(self, audit: AuditLog, publish: Publish, timeout_s: float = REQUEST_TIMEOUT_S, telemetry=None) -> None:
        self.audit = audit
        self.tm = telemetry
        self._publish = publish
        self.timeout_s = timeout_s
        self.grants: list[Grant] = []
        self._pending: dict[str, tuple[asyncio.Future, Proposal]] = {}

    # ------------------------------------------------------------------ grants
    def grant_covers(self, proposal: Proposal) -> bool:
        if not grant_allowed(proposal.risk):
            return False
        return any(g.action_ids is None or proposal.action_id in g.action_ids for g in self.grants)

    def clear_grants(self) -> None:
        self.grants.clear()

    # ----------------------------------------------------------------- requests
    def needs_user(self, proposal: Proposal, integration_level: str = "native") -> bool:
        """True when `request` will ask the user (no policy denial, no automatic approval)."""
        decision = decide(proposal.risk, integration_level, self.grant_covers(proposal))
        return decision in (Decision.ASK, Decision.ASK_CLICK)

    def pending(self) -> list[Proposal]:
        return [p for fut, p in self._pending.values() if not fut.done()]

    async def request(self, proposal: Proposal, integration_level: str = "native") -> Approval:
        decision = decide(proposal.risk, integration_level, self.grant_covers(proposal))
        self.audit.append(
            "proposal",
            request_id=proposal.id,
            action_id=proposal.action_id,
            params=proposal.params,
            risk=proposal.risk,
            rationale=proposal.rationale,
            decision=decision.value,
        )
        if decision == Decision.DENY:
            self.audit.append("approval", request_id=proposal.id, approved=False, by="policy", via="auto")
            return Approval(False, "policy", "auto")
        if decision == Decision.AUTO:
            by = "grant" if proposal.risk == "reversible" else "auto"
            self.audit.append("approval", request_id=proposal.id, approved=True, by=by, via="auto")
            return Approval(True, by, "auto")

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[proposal.id] = (fut, proposal)
        asked_at = time.monotonic()
        await self._emit(
            {
                "type": "permission.request",
                "request_id": proposal.id,
                "action_id": proposal.action_id,
                "title": proposal.title,
                "target": proposal.target_label,
                "risk": proposal.risk,
                "reversible": proposal.reversible,
                "rationale": proposal.rationale,
                "preview": proposal.preview,
                "voice_allowed": voice_may_approve(proposal.risk),
                "can_grant": grant_allowed(proposal.risk),
                "timeout_s": self.timeout_s,
            }
        )
        try:
            approval: Approval = await asyncio.wait_for(fut, self.timeout_s)
        except TimeoutError:
            approval = Approval(False, "timeout", "auto")
        finally:
            self._pending.pop(proposal.id, None)
        if self.tm is not None:
            self.tm.emit(
                "permission",
                request_id=proposal.id,
                action_id=proposal.action_id,
                risk=proposal.risk,
                policy=decision.value,
                approved=approval.approved,
                by=approval.by,
                via=approval.via,
                duration_ms=round((time.monotonic() - asked_at) * 1000, 1),
            )
        self.audit.append(
            "approval", request_id=proposal.id, approved=approval.approved, by=approval.by, via=approval.via
        )
        await self._emit(
            {"type": "permission.resolved", "request_id": proposal.id, "approved": approval.approved, "by": approval.by}
        )
        return approval

    def respond(self, request_id: str, decision: str, via: str = "click") -> tuple[bool, str]:
        """Called with the user's answer. Returns (accepted, reason)."""
        entry = self._pending.get(request_id)
        if entry is None:
            return False, "unknown or expired request"
        fut, proposal = entry
        if fut.done():
            return False, "already answered"
        if via not in ("click", "voice"):
            return False, f"unknown channel {via!r}"
        if via == "voice" and not voice_may_approve(proposal.risk):
            return False, "irreversible actions need an explicit click"
        if proposal.risk == "irreversible" and decision != "deny" and via != "click":
            return False, "irreversible actions need an explicit click"
        if decision == "deny":
            fut.set_result(Approval(False, "user", via))
            return True, "denied"
        if decision == "grant_lesson":
            if not grant_allowed(proposal.risk):
                return False, "only reversible actions can be granted"
            self.grants.append(Grant(scope="session", action_ids={proposal.action_id}))
            fut.set_result(Approval(True, "user", via))
            return True, "approved with grant"
        if decision == "approve":
            fut.set_result(Approval(True, "user", via))
            return True, "approved"
        return False, f"unknown decision {decision!r}"

    def cancel_all(self) -> None:
        for fut, _ in list(self._pending.values()):
            if not fut.done():
                fut.set_result(Approval(False, "cancelled", "auto"))

    async def _emit(self, message: dict[str, Any]) -> None:
        result = self._publish(message)
        if asyncio.iscoroutine(result):
            await result
