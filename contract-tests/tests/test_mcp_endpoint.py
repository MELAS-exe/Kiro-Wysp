"""The MCP endpoint: an external AI agent drives the tutor; every Core guarantee still holds.

Real Core (external mode) + mock adapter + a Panel-like client + a real MCP client over HTTP.
No model is ever called."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from wysp_mock.kanban import card_ref

CARDS = [card_ref("c1"), card_ref("c2"), card_ref("c3")]


@asynccontextmanager
async def agent(stack, token: str | None = None):
    """An MCP client authenticated like a user-configured agent (Authorization: Bearer <pairing token>)."""
    token = token if token is not None else stack.app.state.token
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    async with Client(streamable_http_client(f"http://127.0.0.1:{stack.port}/mcp", http_client=http)) as client:
        yield client
    await http.aclose()


async def call(client: Client, name: str, **arguments):
    result = await client.call_tool(name, arguments)
    return json.loads(result.content[0].text), result


async def test_prop_mcp_requires_the_pairing_token_and_an_allowed_origin(make_stack):
    """CORE-P12: no token, a wrong token or a foreign browser origin never reaches the tools."""
    s = await make_stack([], external=True)
    url = f"http://127.0.0.1:{s.port}/mcp"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    async with httpx.AsyncClient(timeout=5) as http:
        assert (await http.post(url, json=body)).status_code == 401
        assert (await http.post(url, json=body, headers={"Authorization": "Bearer nope"})).status_code == 401
        good = {"Authorization": f"Bearer {s.app.state.token}"}
        assert (await http.post(url, json=body, headers={**good, "Origin": "http://evil.example"})).status_code == 403


async def test_mcp_is_off_when_the_core_has_its_own_llm(make_stack):
    s = await make_stack([])
    async with httpx.AsyncClient(timeout=5) as http:
        health = (await http.get(f"http://127.0.0.1:{s.port}/api/health")).json()
        assert health["mcp"] is None
        assert (await http.post(f"http://127.0.0.1:{s.port}/mcp", json={})).status_code in (404, 405)


async def test_agent_lists_the_closed_tool_set(make_stack):
    s = await make_stack([], external=True)
    async with agent(s) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert {"observe", "narrate", "show_entities", "propose_action", "get_tutor_context", "wait_for_user"} <= names
    # The set is closed: nothing that executes code or approves an action.
    assert not {n for n in names if any(w in n for w in ("exec", "eval", "shell", "approve", "respond"))}


async def test_agent_gets_context_observes_and_teaches(make_stack):
    s = await make_stack([], external=True)
    async with agent(s) as client:
        ctx, _ = await call(client, "get_tutor_context")
        assert ctx["ok"] and "<app_data>" in ctx["context"] and "narrate" in ctx["context"]
        obs, _ = await call(client, "observe", level="full")
        assert obs["ok"] and {e["ref"] for e in obs["entities"]} >= set(CARDS)
        out, _ = await call(
            client,
            "narrate",
            board={"show": CARDS, "layout": "graph"},
            segments=[{"text": "These are the cards on your board.", "provenance": "observed"}],
        )
        assert out["ok"]
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    board = s.session.board
    assert len(board.nodes) == 3 and all(n.provenance == "observed" for n in board.nodes)
    assert all(n.ref in s.session.observed_refs for n in board.nodes)


async def test_prop_agent_cannot_create_observed_facts(make_stack):
    """CORE-P2 through MCP: the provenance rules do not depend on who drives the tools."""
    s = await make_stack([], external=True)
    async with agent(s) as client:
        out, _ = await call(client, "add_concept", label="Fake", provenance="observed")
        assert out["ok"]
    nodes = s.session.board.nodes
    assert len(nodes) == 1 and nodes[0].provenance in ("inferred", "illustrative") and nodes[0].ref is None


async def test_user_messages_reach_the_agent_not_a_model(make_stack):
    s = await make_stack([], external=True)
    async with agent(s) as client:
        empty, _ = await call(client, "wait_for_user", timeout_s=1)
        assert empty["events"] == [] and empty["timed_out"] is True
        await s.ui.send(type="user.message", text="what are these cards?", source="typed")
        got, _ = await call(client, "wait_for_user", timeout_s=5)
        assert [e["text"] for e in got["events"]] == ["what are these cards?"]
        assert got["events"][0]["kind"] == "message" and got["status"] == "thinking"
        await s.ui.send(type="user.interrupt")
        got, _ = await call(client, "wait_for_user", timeout_s=5)
        assert [e["kind"] for e in got["events"]] == ["interrupt"]


async def test_message_without_an_agent_tells_the_user(make_stack):
    s = await make_stack([], external=True)
    await s.ui.send(type="user.message", text="hello?")
    seg = await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    assert "No AI assistant is connected" in seg["segment"]["text"]


async def test_prop_agent_action_needs_the_users_approval_and_is_verified(make_stack):
    """CORE-P5 through MCP: the agent proposes, the user approves in the Panel, Wysp verifies."""
    s = await make_stack([], external=True)
    async with agent(s) as client:
        task = asyncio.create_task(
            call(
                client,
                "propose_action",
                action_id="move_card",
                params={"card": card_ref("c3"), "column": "doing"},
                mode="do",
                rationale="user asked",
            )
        )
        req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
        assert s.mock.cards["c3"]["column"] == "todo", "nothing may run before approval"
        await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve", via="click")
        out, _ = await asyncio.wait_for(task, 15)
    assert out["ok"], out
    assert s.mock.cards["c3"]["column"] == "doing"
    kinds = [r["kind"] for r in s.audit if r["kind"] in ("proposal", "approval", "execution")]
    assert kinds == ["proposal", "approval", "execution"]


async def test_read_only_action_returns_its_text_without_a_dialog(make_stack):
    """A read-only action runs without approval, even when the agent asks for 'guide', and its text comes back."""
    s = await make_stack([], external=True)
    async with agent(s) as client:
        out, _ = await asyncio.wait_for(
            call(client, "propose_action", action_id="describe_card", params={"card": card_ref("c3")}, mode="guide"),
            15,
        )
    assert out == {"ok": True, "status": "done", "output": "Record the demo is in todo"}, out
    assert not [m for m in s.ui.messages if m.get("type") == "permission.request"], "reading asks nothing"
    kinds = [r["kind"] for r in s.audit if r["kind"] in ("proposal", "approval", "execution")]
    assert kinds == ["proposal", "approval", "execution"], "a read is still audited"
    assert s.mock.cards["c3"]["column"] == "todo"


async def test_denied_action_changes_nothing_through_mcp(make_stack):
    s = await make_stack([], external=True)
    async with agent(s) as client:
        task = asyncio.create_task(
            call(
                client,
                "propose_action",
                action_id="move_card",
                params={"card": card_ref("c3"), "column": "done"},
                mode="do",
            )
        )
        req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
        await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="deny")
        out, result = await asyncio.wait_for(task, 15)
    assert s.mock.cards["c3"]["column"] == "todo"
    assert not [r for r in s.audit if r["kind"] == "execution"]
    assert out is not None and result is not None
