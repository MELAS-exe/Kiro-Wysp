"""Permission policy, data-driven by risk level (see .kiro/steering/trust-and-safety.md)."""

from __future__ import annotations

from enum import StrEnum


class Decision(StrEnum):
    AUTO = "auto"  # runs without asking, logged
    ASK = "ask"  # click or spoken "yes" or an active lesson grant
    ASK_CLICK = "ask_click"  # explicit click with a preview, never by voice, never by grant
    DENY = "deny"  # not allowed in this context


def decide(risk: str, integration_level: str = "native", grant_covers: bool = False) -> Decision:
    if risk in ("read_only", "ui_state"):
        return Decision.AUTO
    if risk == "reversible":
        return Decision.AUTO if grant_covers else Decision.ASK
    if risk == "irreversible":
        return Decision.DENY if integration_level == "visual" else Decision.ASK_CLICK
    return Decision.DENY  # unknown risk levels are never allowed


def voice_may_approve(risk: str) -> bool:
    return risk != "irreversible"


def grant_allowed(risk: str) -> bool:
    return risk == "reversible"
