"""Gate and pipeline properties CORE-P4, CORE-P5, CORE-P6 [core-orchestrator 7.1].

Random proposals of the mock adapter's actions go through the real `propose_action` pipeline, the permission gate
and an auto-responder that plays the user (random decision and channel). The application is the in-process
MockKanban, so nothing leaves the process.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from test_prop_provenance import make_session
from wysp_core.contract import ActionCall
from wysp_core.orchestrator.tools import ToolBox
from wysp_core.trust.gate import PermissionGate
from wysp_core.trust.policy import Decision, decide

FAST = settings(max_examples=40, deadline=None)

RISK = {
    "create_card": "reversible",
    "move_card": "reversible",
    "rename_card": "reversible",
    "select_card": "ui_state",
    "archive_card": "irreversible",
    "describe_card": "read_only",
}
ACTIONS = sorted(RISK)
COLUMNS = ["todo", "doing", "done"]
user_reply = st.tuples(
    st.sampled_from(["approve", "deny", "grant_lesson"]), st.sampled_from(["click", "voice"]), st.booleans()
)  # decision, channel, whether to retry with a click when the Core refuses the channel


def args_for(action_id: str, i: int, column: str, title: str) -> dict[str, Any]:
    card = f"mock://card/c{1 + i % 3}"
    return {
        "create_card": {"title": title, "column": column},
        "move_card": {"card": card, "column": column},
        "rename_card": {"card": card, "title": title},
        "select_card": {"card": card},
        "archive_card": {"card": card},
        "describe_card": {"card": card},
    }[action_id]


proposal_st = st.tuples(
    st.sampled_from(ACTIONS),
    st.integers(0, 5),
    st.sampled_from(COLUMNS),
    st.text(alphabet="abcdefgh ", min_size=1, max_size=10).filter(lambda s: s.strip()),
    user_reply,
)


async def answer_requests(session, replies: list[tuple[str, str, bool]], log: list[dict[str, Any]]) -> None:
    """The user: answers every pending permission request with the next scripted reply."""
    n = 0
    while True:
        for proposal in session.gate.pending():
            decision, via, retry = replies[n % len(replies)]
            n += 1
            ok, _ = session.gate.respond(proposal.id, decision, via)
            log.append({"id": proposal.id, "decision": decision, "via": via, "accepted": ok})
            if not ok and retry:
                ok, _ = session.gate.respond(proposal.id, decision, "click")
                log.append({"id": proposal.id, "decision": decision, "via": "click", "accepted": ok})
            if not ok:  # still refused (or no retry): the user gives up and denies
                session.gate.respond(proposal.id, "deny", "click")
        await asyncio.sleep(0.001)


# ------------------------------------------------------------------------------ CORE-P4 and P5
@FAST
@given(st.lists(proposal_st, min_size=1, max_size=6))
def test_prop_core_p4_p5_gate_policy_and_audit_completeness(proposals) -> None:
    """CORE-P4: an action executes only if the policy allows it (irreversible only after an explicit click, never by
    voice or grant; read_only and ui_state never ask). CORE-P5: every `execution` record is preceded by an approval
    record, with the same request id, that approved it."""

    async def scenario() -> None:
        session, conn = make_session()
        session.gate.timeout_s = 2.0  # a safety net: the responder answers every request
        tools = ToolBox(session)
        replies = [p[4] for p in proposals]
        responses: list[dict[str, Any]] = []
        responder = asyncio.create_task(answer_requests(session, replies, responses))
        try:
            for action_id, i, column, title, _ in proposals:
                params = args_for(action_id, i, column, title)
                if action_id == "archive_card" and f"c{1 + i % 3}" not in conn.mock.cards:
                    continue
                await tools.call("propose_action", {"action_id": action_id, "params": params, "mode": "do"})
        finally:
            responder.cancel()
        records = session.audit.records
        risk_of = {r["request_id"]: RISK[r["action_id"]] for r in records if r["kind"] == "proposal"}
        asked = {m["request_id"] for m in session.hub.sent if m["type"] == "permission.request"}
        for rid, risk in risk_of.items():
            if risk in ("read_only", "ui_state"):
                assert rid not in asked, "a read-only or ui-state action prompted the user"
        voice_requests = {m["request_id"]: m for m in session.hub.sent if m["type"] == "permission.request"}
        for rid, m in voice_requests.items():
            assert m["voice_allowed"] == (risk_of[rid] != "irreversible")
            assert m["can_grant"] == (risk_of[rid] == "reversible")
        executions = [r for r in records if r["kind"] == "execution"]
        for ex in executions:
            rid = ex["request_id"]
            before = records[: records.index(ex)]
            approvals = [r for r in before if r["kind"] == "approval" and r["request_id"] == rid]
            assert approvals and approvals[-1]["approved"] is True, "execution without a preceding approval (P5)"
            risk = risk_of[rid]
            decision = decide(risk, "native", grant_covers=approvals[-1]["by"] == "grant")
            assert decision != Decision.DENY, "executed although the policy denies it (P4)"
            if risk == "irreversible":
                assert approvals[-1]["by"] == "user" and approvals[-1]["via"] == "click", approvals[-1]
            if risk in ("read_only", "ui_state"):
                assert approvals[-1]["by"] == "auto"
        # an irreversible action that ran was clicked: no accepted voice answer exists for it
        for r in responses:
            if r["via"] == "voice" and r["accepted"]:
                assert risk_of[r["id"]] != "irreversible"
        # nothing executes twice for one proposal
        ids = [e["request_id"] for e in executions]
        assert len(ids) == len(set(ids))

    asyncio.run(scenario())


proposal_risk_st = st.sampled_from(["read_only", "ui_state", "reversible", "irreversible", "bogus"])


@FAST
@given(
    proposal_risk_st,
    st.sampled_from(["native", "interface", "visual"]),
    st.lists(st.booleans(), max_size=2),
    st.sampled_from(["approve", "deny", "grant_lesson"]),
    st.sampled_from(["click", "voice", "pigeon"]),
)
def test_prop_core_p4_gate_decisions_for_any_proposal(risk, level, grants, decision, via) -> None:
    """CORE-P4 at the gate itself, for any risk, integration level, grant state and reply."""
    from wysp_core.trust.audit import AuditLog
    from wysp_core.trust.gate import Grant, Proposal

    async def scenario() -> None:
        sent: list[dict[str, Any]] = []

        async def publish(m: dict[str, Any]) -> None:
            sent.append(m)

        gate = PermissionGate(AuditLog(None), publish, timeout_s=0.2)
        gate.grants = [Grant(scope="session", action_ids={"act"}) for _ in grants[:1]] if any(grants) else []
        proposal = Proposal("act", "Act", {}, "why", risk, risk == "reversible")
        task = asyncio.create_task(gate.request(proposal, level))
        await asyncio.sleep(0.01)
        accepted = False
        if gate.pending():
            accepted, _ = gate.respond(proposal.id, decision, via)
        approval = await task
        asked = any(m["type"] == "permission.request" for m in sent)
        if risk in ("read_only", "ui_state"):
            assert approval.approved and not asked
        elif risk == "irreversible":
            assert not (approval.approved and via != "click"), "an irreversible action was approved off-click"
            assert not (approval.approved and approval.by in ("grant", "auto"))
            if level == "visual":
                assert not approval.approved and not asked
        elif risk == "reversible" and approval.approved:
            assert approval.by in ("user", "grant")
            assert approval.by == "grant" or (accepted and decision in ("approve", "grant_lesson"))
        elif risk == "bogus":
            assert not approval.approved
        if approval.approved and approval.by == "user":
            assert accepted and decision != "deny"

    asyncio.run(scenario())


# ------------------------------------------------------------------------------------- CORE-P6
lie_st = st.sampled_from(["none", "wrong_result_with_token", "wrong_result_without_token"])


@FAST
@given(
    st.sampled_from(["create_card", "move_card", "rename_card"]),
    st.integers(0, 5),
    st.sampled_from(COLUMNS),
    st.text(alphabet="abcdefgh ", min_size=1, max_size=10).filter(lambda s: s.strip()),
    lie_st,
)
def test_prop_core_p6_failed_postconditions_are_undone_and_reported(action_id, i, column, title, lie) -> None:
    """CORE-P6: an executed action whose postconditions fail is undone when an undo token exists, and the outcome
    reported is `failed`; a truthful action is reported `verified` and stays."""

    async def scenario() -> None:
        session, conn = make_session()
        session.gate.grants.append(__import__("wysp_core.trust.gate", fromlist=["Grant"]).Grant("session", None))
        params = args_for(action_id, i, column, title)
        if action_id == "move_card":  # a lie needs a card that is not already in the target column
            ref = params["card"]
            conn.mock.cards[ref.rsplit("/", 1)[-1]]["column"] = "todo"
            params["column"] = "doing" if column == "todo" else column
        if lie != "none":

            def tamper(call: ActionCall) -> ActionCall:  # the adapter does something else than asked
                p = dict(call.params)
                if call.action_id == "move_card":
                    p["column"] = "todo"
                elif "title" in p:
                    p["title"] = p["title"] + " (other)"
                return call.model_copy(update={"params": p})

            conn.tamper = tamper
            if lie == "wrong_result_without_token":
                conn.tamper_result = lambda r: r.model_copy(update={"undo_token": None})
        before_cards = {k: dict(v) for k, v in conn.mock.cards.items()}
        out = await ToolBox(session).call("propose_action", {"action_id": action_id, "params": params, "mode": "do"})
        after_cards = {k: dict(v) for k, v in conn.mock.cards.items()}
        undo_records = [r for r in session.audit.records if r["kind"] == "undo"]
        if lie == "none":
            assert out["status"] == "verified" and not undo_records
        elif lie == "wrong_result_with_token":
            assert out["ok"] is False and out["status"] == "failed_and_undone", out
            assert len(undo_records) == 1 and undo_records[0]["by"] == "auto"
            assert after_cards == before_cards, "the failed action was not undone"
        else:
            assert out["ok"] is False and out["status"] == "failed", out
            assert not undo_records  # no token, nothing to undo: reported failed with evidence
        if lie != "none":
            verification = [r for r in session.audit.records if r["kind"] == "verification"]
            assert verification and verification[-1]["ok"] is False

    asyncio.run(scenario())
