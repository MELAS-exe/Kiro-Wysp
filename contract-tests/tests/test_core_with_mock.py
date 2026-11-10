"""End-to-end tests: real Core + mock adapter + a Panel-like client, with a scripted LLM."""

from __future__ import annotations

import asyncio

import httpx
from wysp_mock.kanban import card_ref

CARDS = [card_ref("c1"), card_ref("c2"), card_ref("c3")]


async def _get_json(url: str) -> dict:
    async with httpx.AsyncClient(timeout=5) as client:
        return (await client.get(url)).json()


def say(text: str) -> dict:
    return {"after_tool": "propose_action", "say": text}


async def test_handshake_health_and_initial_state(make_stack):
    s = await make_stack([])
    health = await _get_json(f"http://127.0.0.1:{s.port}/api/health")
    assert health["adapters"][0]["adapter_id"] == "mock-kanban"
    assert health["contract_version"] == "1.0.0"
    state = await s.ui.wait_for(lambda m: m.get("type") == "session.state")
    assert state["active_adapter"] == "mock-kanban"
    assert s.ui.of_type("board.snapshot")


async def test_bad_token_is_refused(make_stack):
    from wysp_mock.cli import start_mock

    s = await make_stack([], connect_mock=False)
    _app, client = start_mock(f"ws://127.0.0.1:{s.port}/ws/adapter", "not-the-token")
    for _ in range(100):
        if client.status == "refused":
            break
        await asyncio.sleep(0.05)
    await asyncio.to_thread(client.stop)
    assert client.status in ("refused", "stopped")
    assert "refused" in (client.last_error or "") or client.status == "refused"
    assert not s.session.registry.all()


async def test_show_entities_builds_an_observed_board(make_stack):
    s = await make_stack(
        [
            {"when": "show", "calls": [{"name": "show_entities", "arguments": {"refs": CARDS, "layout": "graph"}}]},
            {"after_tool": "show_entities", "say": "These are the cards on your board."},
        ]
    )
    await s.ui.send(type="user.message", text="show me the cards")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    board = s.session.board
    assert len(board.nodes) == 3
    assert all(n.provenance == "observed" and n.ref in CARDS for n in board.nodes)
    # CORE-P1: every observed node is backed by an observation of this session
    assert all(n.ref in s.session.observed_refs for n in board.nodes if n.provenance == "observed")
    assert board.layout == "graph"


async def test_llm_cannot_create_observed_facts(make_stack):
    """CORE-P2: add_concept can never produce an 'observed' node, even if the LLM claims it."""
    s = await make_stack(
        [
            {
                "when": "concept",
                "calls": [{"name": "add_concept", "arguments": {"label": "Fake", "provenance": "observed"}}],
            },
            {"after_tool": "add_concept", "say": "ok"},
        ]
    )
    await s.ui.send(type="user.message", text="add a concept")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    nodes = s.session.board.nodes
    assert len(nodes) == 1 and nodes[0].provenance in ("inferred", "illustrative") and nodes[0].ref is None


async def test_validator_downgrades_unbacked_observed_nodes(make_stack):
    s = await make_stack([])
    node = {
        "id": "n:mock://card/ghost",
        "ref": "mock://card/ghost",
        "kind": "card",
        "label": "Ghost",
        "provenance": "observed",
    }
    result = await s.session.apply_board([{"op": "add_node", "node": node}])
    assert result["ok"] and result["warnings"]
    assert s.session.board.node("n:mock://card/ghost").provenance == "inferred"


async def test_do_action_requires_approval_then_verifies(make_stack):
    s = await make_stack(
        [
            {"when": "move", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "doing"}, "mode": "do", "rationale": "user asked"}}]},
            say("Moved."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="please move the demo card")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    assert req["risk"] == "reversible" and req["voice_allowed"] is True
    assert s.mock.cards["c3"]["column"] == "todo", "nothing may run before approval"
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve", via="click")
    ev = await s.ui.wait_for(lambda m: m.get("type") == "evidence.added")
    assert ev["evidence"]["type"] == "verified" and ev["scope"] == "wysp_action"
    assert s.mock.cards["c3"]["column"] == "doing"
    # CORE-P5: an approval record precedes the execution record with the same request id
    kinds = [(r["kind"], r.get("request_id")) for r in s.audit if r["kind"] in ("proposal", "approval", "execution")]
    assert [k for k, _ in kinds] == ["proposal", "approval", "execution"]
    assert len({rid for _, rid in kinds}) == 1


async def test_denied_action_changes_nothing(make_stack):
    s = await make_stack(
        [
            {"when": "move", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "done"}, "mode": "do"}}]},
            say("Understood, I will not move it."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="move it")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="deny")
    await s.ui.wait_for(lambda m: m.get("type") == "permission.resolved" and m["approved"] is False)
    assert s.mock.cards["c3"]["column"] == "todo"
    assert not [r for r in s.audit if r["kind"] == "execution"]


async def test_irreversible_needs_a_click_never_voice(make_stack):
    """CORE-P4: irreversible actions are not approvable by voice."""
    s = await make_stack(
        [
            {"when": "archive", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "archive_card", "params": {"card": card_ref("c1")}, "mode": "do"}}]},
            say("Archived."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="archive the first card")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    assert req["risk"] == "irreversible" and req["voice_allowed"] is False and req["can_grant"] is False
    assert req["preview"] == {"would_archive": "Write the spec"}
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve", via="voice")
    err = await s.ui.wait_for(lambda m: m.get("type") == "error" and m.get("code") == "permission_refused")
    assert "click" in err["message"]
    assert "c1" in s.mock.cards
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve", via="click")
    await s.ui.wait_for(lambda m: m.get("type") == "evidence.added")
    assert "c1" not in s.mock.cards


async def test_failed_verification_triggers_automatic_undo(make_stack):
    """CORE-P6: if postconditions fail, the action is undone and reported as failed."""
    from wysp_adapter_sdk import ActionOutcome

    undone: list[int] = []
    s = await make_stack(
        [
            {"when": "move", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "done"}, "mode": "do"}}]},
            say("It did not work."),
        ]
    )  # fmt: skip
    spec, _real = s.mock.registry._actions["move_card"]
    s.mock.registry._actions["move_card"] = (
        spec,
        lambda p, dry: ActionOutcome(changed=[p["card"]], undo=lambda: undone.append(1)),  # lies: changes nothing
    )
    await s.ui.send(type="user.message", text="move it")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment" and "did not work" in m["segment"]["text"])
    assert undone == [1]
    assert [r for r in s.audit if r["kind"] == "verification" and r["ok"] is False]
    assert [r for r in s.audit if r["kind"] == "undo" and r["by"] == "auto"]
    assert not s.ui.of_type("evidence.added")


async def test_guide_mode_verifies_the_users_own_change(make_stack):
    s = await make_stack(
        [
            {"when": "teach", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "doing"}, "mode": "guide"}}]},
            say("Go ahead and drag the card."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="teach me to move a card")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    steps = s.session.board.steps
    assert steps and steps[0].status == "active" and "Record the demo" in steps[0].text
    assert s.session.watch is not None
    # a change made by Wysp itself must never count
    s.mock.cards["c3"]["column"] = "doing"
    s.mock.report_change([card_ref("c3")], origin="wysp")
    await asyncio.sleep(1.2)
    assert not s.ui.of_type("evidence.added")
    s.mock.cards["c3"]["column"] = "todo"
    # the user does it
    s.mock.simulate_user("move_card", {"card": card_ref("c3"), "column": "doing"})
    ev = await s.ui.wait_for(lambda m: m.get("type") == "evidence.added")
    assert ev["scope"] == "user_action"
    assert all(st.status == "done" for st in s.session.board.steps)
    assert s.session.watch is None


async def test_guide_mode_skips_when_already_satisfied(make_stack):
    s = await make_stack(
        [
            {"when": "teach", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c1"), "column": "done"}, "mode": "guide"}}]},
            say("It is already there."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="teach me")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    assert s.session.watch is None and not s.session.board.steps


async def test_interrupt_then_resume_replays_exactly_the_unplayed_segments(make_stack):
    """CORE-P7 / CORE-P8."""
    s = await make_stack(
        [
            {"when": "explain", "calls": [{"name": "narrate", "arguments": {"segments": [
                {"text": "First idea."}, {"text": "Second idea."}, {"text": "Third idea."}]}}]},
            {"after_tool": "narrate"},
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="explain it")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment" and m["segment"]["index"] == 2)
    segs = [m["segment"] for m in s.ui.of_type("narration.segment")]
    await s.ui.send(type="narration.progress", segment_id=segs[0]["id"], played=True)
    await asyncio.sleep(0.2)
    await s.ui.send(type="user.interrupt")
    cancel = await s.ui.wait_for(lambda m: m.get("type") == "narration.cancel")
    assert cancel["from_index"] == 1
    before = len(s.ui.of_type("narration.segment"))
    await s.ui.send(type="user.continue")
    await s.ui.wait_for(lambda m: len(s.ui.of_type("narration.segment")) >= before + 2)
    replayed = [m["segment"]["text"] for m in s.ui.of_type("narration.segment")[before:]]
    assert replayed == ["Second idea.", "Third idea."]


async def test_adapter_events_keep_the_board_in_sync(make_stack):
    s = await make_stack(
        [
            {"when": "show", "calls": [{"name": "show_entities", "arguments": {"refs": [card_ref("c3")], "layout": "tree"}}]},
            {"after_tool": "show_entities", "say": "Here is the card."},
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="show the card")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    s.mock.simulate_user("rename_card", {"card": card_ref("c3"), "title": "Record the final demo"})
    for _ in range(100):
        node = s.session.board.node("n:" + card_ref("c3"))
        if node and node.label == "Record the final demo":
            break
        await asyncio.sleep(0.05)
    assert s.session.board.node("n:" + card_ref("c3")).label == "Record the final demo"


async def test_undo_last_restores_the_state(make_stack):
    s = await make_stack(
        [
            {"when": "move", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "done"}, "mode": "do"}}]},
            say("Moved."),
        ]
    )  # fmt: skip
    before = s.mock.snapshot()
    await s.ui.send(type="user.message", text="move it")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve")
    await s.ui.wait_for(lambda m: m.get("type") == "evidence.added")
    assert s.mock.cards["c3"]["column"] == "done"
    await s.ui.send(type="undo.last")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment" and "Undone" in m["segment"]["text"])
    assert s.mock.snapshot() == before


async def test_turn_ends_once_wysp_has_spoken(make_stack):
    """After show_entities + narrate in one response, no further LLM request is made (rate-limited tiers)."""
    s = await make_stack(
        [
            {"when": "explain", "calls": [
                {"name": "show_entities", "arguments": {"refs": CARDS[:1], "layout": "tree"}},
                {"name": "narrate", "arguments": {"segments": [{"text": "This is your first card."}]}}]},
            {"after_tool": "narrate", "say": "EXTRA ROUND"},
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="explain the card")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    await s.session.wait_for_turn()
    texts = [m["segment"]["text"] for m in s.ui.of_type("narration.segment")]
    assert texts == ["This is your first card."]
    assert len(s.session.board.nodes) == 1


async def test_permission_is_announced_and_survives_a_repeated_request(make_stack):
    """A repeated message while an approval is pending reminds the user instead of cancelling the request."""
    s = await make_stack(
        [
            {"when": "move", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "doing"}, "mode": "do"}}]},
            say("Moved."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="Can you move it for me?")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    spoken = [m["segment"]["text"] for m in s.ui.of_type("narration.segment")]
    assert any("approval" in t for t in spoken), spoken
    await s.ui.send(type="user.message", text="can you move it for me")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment" and "still waiting" in m["segment"]["text"])
    assert not s.ui.of_type("permission.resolved"), "the pending request must not be cancelled"
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve")
    await s.ui.wait_for(lambda m: m.get("type") == "evidence.added")
    assert s.mock.cards["c3"]["column"] == "doing"


async def test_a_different_message_still_cancels_a_pending_request(make_stack):
    s = await make_stack(
        [
            {"when": "move", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "doing"}, "mode": "do"}}]},
            say("Moved."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="move it")
    await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    await s.ui.send(type="user.message", text="actually, never mind")
    resolved = await s.ui.wait_for(lambda m: m.get("type") == "permission.resolved")
    assert resolved["approved"] is False and resolved["by"] == "cancelled"
    assert s.mock.cards["c3"]["column"] == "todo"


async def test_ui_messages_are_logged_with_their_client(make_stack):
    s = await make_stack([])
    await s.ui.send(type="undo.last")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    recs = [r for r in s.session.tm.ring if r["kind"] == "ui.message"]
    assert recs and recs[-1]["type"] == "undo.last" and recs[-1]["client"] in ("browser", "native")


async def test_tts_endpoint(make_stack):
    """No real voice in tests: a fake provider stands in for the local one."""
    s = await make_stack([])

    class FakeTTS:
        name, mime = "fake", "audio/wav"

        async def synth(self, text: str, lang: str = "en") -> bytes:
            return b"RIFF" + text.encode()

    s.app.state.tts = FakeTTS()
    url = f"http://127.0.0.1:{s.port}/api/tts"
    async with httpx.AsyncClient(timeout=5) as client:
        ok = await client.post(url, json={"text": "Hello\x00 there"})
        assert ok.status_code == 200 and ok.content == b"RIFFHello there"
        assert ok.headers["content-type"].startswith("audio/wav")
        assert "access-control-allow-origin" not in ok.headers
        evil = await client.post(url, json={"text": "hi"}, headers={"Origin": "https://evil.example"})
        assert evil.status_code == 403
        empty = await client.post(url, json={"text": "   "})
        assert empty.status_code == 400


async def test_ocr_endpoint(make_stack):
    """Hybrid adapters ask where text is on their own screenshot. A fake engine stands in for Windows OCR."""
    s = await make_stack([])
    seen: list[int] = []

    class FakeOcr:
        name = "fake"

        async def recognize(self, image: bytes) -> dict:
            seen.append(len(image))
            return {
                "width": 10,
                "height": 10,
                "lines": [{"text": "Add", "words": [{"text": "Add", "x": 1, "y": 2, "w": 3, "h": 4}]}],
            }

    s.app.state.ocr = FakeOcr()
    url = f"http://127.0.0.1:{s.port}/api/ocr"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    async with httpx.AsyncClient(timeout=5) as client:
        ok = await client.post(url, content=png, headers={"Content-Type": "image/png"})
        assert ok.status_code == 200 and ok.json()["lines"][0]["text"] == "Add" and seen == [len(png)]
        assert "access-control-allow-origin" not in ok.headers
        assert (await client.post(url, content=b"not a png")).status_code == 415
        evil = await client.post(url, content=png, headers={"Origin": "https://evil.example"})
        assert evil.status_code == 403
    recs = [r for r in s.session.tm.ring if r["kind"] == "ocr.recognize"]
    assert recs and "image" not in recs[-1] and recs[-1]["bytes"] == len(png)  # sizes only, never the picture
