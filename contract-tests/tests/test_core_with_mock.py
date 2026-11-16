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
    assert health["contract_version"] == "1.1.0"
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
    assert req["preview"] == {"from": "todo", "to": "doing"}, "a reversible change shows what it would do"
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


async def test_wysp_doing_a_guided_step_never_credits_the_user(make_stack):
    """Trust rule: only user actions count. When Wysp performs the step the user was guided through, the
    selection change its action causes (selection events carry no origin) and any later user change must not
    complete the guided step as the user's achievement."""
    s = await make_stack(
        [
            {"when": "teach", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "doing"}, "mode": "guide"}}]},
            say("Go ahead and drag the card."),
            {"when": "do it", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "doing"}, "mode": "do"}}]},
            say("Moved."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="teach me to move a card")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    assert s.session.watch is not None
    await s.ui.send(type="user.message", text="do it for me")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve")
    await s.ui.wait_for(lambda m: m.get("type") == "evidence.added" and m["scope"] == "wysp_action")
    # The action moved the user's focus: the adapter reports it, without an origin (the contract has none).
    s.mock.report_selection([card_ref("c3")])
    await asyncio.sleep(1.2)
    # Later the user changes something unrelated: the guided goal is still true, but Wysp did it.
    s.mock.simulate_user("rename_card", {"card": card_ref("c1"), "title": "Write the final spec"})
    await asyncio.sleep(1.2)
    assert not [m for m in s.ui.of_type("evidence.added") if m["scope"] == "user_action"]
    assert not [r for r in s.audit if r["kind"] == "guide_verified"]
    assert s.session.watch is None, "the guided step is closed: Wysp did it"


async def test_a_failed_wysp_action_keeps_the_guided_step_open(make_stack):
    """Review finding: a Wysp action that fails verification and is undone must not close the guided step."""
    from wysp_adapter_sdk import ActionOutcome

    s = await make_stack(
        [
            {"when": "teach", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "doing"}, "mode": "guide"}}]},
            say("Go ahead and drag the card."),
            {"when": "do it", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "rename_card", "params": {"card": card_ref("c3"), "title": "Demo"}, "mode": "do"}}]},
            say("It did not work."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="teach me to move a card")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    # A faulty rename: it moves the card (reaching the guided goal) but does not rename it, so its own
    # verification fails and the Core undoes it.
    spec, _real = s.mock.registry._actions["rename_card"]

    def faulty(p, dry):
        s.mock.cards["c3"]["column"] = "doing"
        return ActionOutcome(changed=[p["card"]], undo=lambda: s.mock.cards["c3"].update(column="todo"))

    s.mock.registry._actions["rename_card"] = (spec, faulty)
    await s.ui.send(type="user.message", text="do it for me")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment" and "did not work" in m["segment"]["text"])
    assert s.session.watch is not None, "the user can still do the step"
    assert all(st.status != "done" for st in s.session.board.steps)
    assert not [r for r in s.audit if r["kind"] == "guide_closed"]


async def test_wysp_undo_reaching_a_guided_goal_never_credits_the_user(make_stack):
    """Review finding: an undo by Wysp that makes a guided step true closes it without crediting the user."""
    s = await make_stack(
        [
            {"when": "move", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "doing"}, "mode": "do"}}]},
            say("Moved."),
            {"when": "teach", "calls": [{"name": "propose_action", "arguments": {
                "action_id": "move_card", "params": {"card": card_ref("c3"), "column": "todo"}, "mode": "guide"}}]},
            say("Drag it back to To do."),
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="move the demo card")
    req = await s.ui.wait_for(lambda m: m.get("type") == "permission.request")
    await s.ui.send(type="permission.respond", request_id=req["request_id"], decision="approve")
    await s.ui.wait_for(lambda m: m.get("type") == "evidence.added")
    await s.ui.send(type="user.message", text="teach me to move it back")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment" and "back" in m["segment"]["text"])
    assert s.session.watch is not None
    await s.ui.send(type="undo.last")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment" and "Undone" in m["segment"]["text"])
    assert s.mock.cards["c3"]["column"] == "todo"
    s.mock.simulate_user("rename_card", {"card": card_ref("c1"), "title": "Write the final spec"})
    await asyncio.sleep(1.2)
    assert not [m for m in s.ui.of_type("evidence.added") if m["scope"] == "user_action"]
    assert s.session.watch is None
    assert [r for r in s.audit if r["kind"] == "guide_closed" and r["by"] == "wysp"]


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


class _FakeRecorder:
    def __init__(self, pcm: bytes) -> None:
        self.pcm, self.rate, self.on = pcm, 16000, False

    def start(self) -> None:
        from wysp_core.listen import ListenError

        if self.on:
            raise ListenError("already listening")
        self.on = True

    def stop(self) -> tuple[bytes, float]:
        from wysp_core.listen import ListenError

        if not self.on:
            raise ListenError("not listening")
        self.on = False
        return self.pcm, len(self.pcm) / 2 / 16000

    def cancel(self) -> None:
        self.on = False


class _FakeWhisper:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, wav: bytes, lang: str = "en", prompt: str = "") -> str:
        self.calls += 1
        assert wav[:4] == b"RIFF"
        return "add a cube"


async def test_listen_endpoints_need_the_token_and_skip_silence(make_stack):
    import array

    from wysp_core.listen import Listener

    s = await make_stack([])
    loud = array.array("h", [8000, -8000] * 8000).tobytes()  # one second of a loud signal
    whisper = _FakeWhisper()
    s.app.state.listener = Listener(_FakeRecorder(loud), whisper)
    base = f"http://127.0.0.1:{s.port}/api/listen"
    auth = {"X-Wysp-Token": s.app.state.token}
    async with httpx.AsyncClient(timeout=5) as client:
        assert (await client.post(base + "/start")).status_code == 401, "no token, no microphone"
        assert (
            await client.post(base + "/start", headers={**auth, "Origin": "https://evil.example"})
        ).status_code == 403
        assert (await client.post(base + "/stop", headers=auth)).status_code == 409
        assert (await client.post(base + "/start", headers=auth)).json()["ok"] is True
        assert (await client.post(base + "/start", headers=auth)).status_code == 409
        heard = (await client.post(base + "/stop", headers=auth)).json()
        assert heard["text"] == "add a cube" and heard["seconds"] == 1.0 and whisper.calls == 1
        # Silence never reaches the speech service (Whisper invents words on silence).
        s.app.state.listener = Listener(_FakeRecorder(b"\x00\x00" * 16000), whisper)
        await client.post(base + "/start", headers=auth)
        quiet = (await client.post(base + "/stop", headers=auth)).json()
        assert quiet["text"] == "" and quiet["silent"] is True and whisper.calls == 1
    recs = [r for r in s.session.tm.ring if r["kind"] == "listen.stop"]
    assert recs and all("audio" not in r and "pcm" not in r for r in recs)


async def test_steps_go_on_the_board_in_one_call_and_chain(make_stack):
    """One add_concept call with several steps instead of one model round per step (rate-limited tiers)."""
    s = await make_stack(
        [
            {"when": "steps", "calls": [
                {"name": "show_entities", "arguments": {"refs": CARDS[:1], "layout": "sequence"}},
                {"name": "add_concept", "arguments": {"items": [
                    {"label": "Open the card", "kind": "step", "attach_to": CARDS[0]},
                    {"label": "Change its column", "kind": "step"},
                    {"label": "Check the board", "kind": "step"}]}},
                {"name": "narrate", "arguments": {"segments": [{"text": "Three steps.", "provenance": "illustrative"}]}}]},
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="show me the steps")
    await s.ui.wait_for(lambda m: m.get("type") == "narration.segment")
    await s.session.wait_for_turn()
    steps = [n for n in s.session.board.nodes if n.kind == "step"]
    assert [n.label for n in steps] == ["Open the card", "Change its column", "Check the board"]
    assert all(n.provenance in ("inferred", "illustrative") for n in steps)
    edges = {(e.source, e.target) for e in s.session.board.edges}
    assert (steps[0].id, steps[1].id) in edges and (steps[1].id, steps[2].id) in edges
    assert any(e.target == steps[0].id and e.source != steps[1].id for e in s.session.board.edges)


async def _turn_done(s, timeout: float = 8.0) -> None:
    """Wait until the Core has recorded a finished turn (the message is handled asynchronously)."""
    for _ in range(int(timeout / 0.02)):
        if any(r["kind"] == "turn" for r in s.session.tm.ring):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("no turn finished")


async def test_observe_with_an_unknown_root_says_so(make_stack):
    s = await make_stack(
        [
            {"when": "look", "calls": [{"name": "observe", "arguments": {"level": "focus", "root": "mock://nothing"}}]},
            {"after_tool": "observe", "say": "ok"},
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="look at it")
    await _turn_done(s)
    calls = [r for r in s.session.tm.ring if r["kind"] == "tool.call" and r.get("tool") == "observe"]
    assert calls and calls[-1]["ok"] is False and "no entity" in calls[-1]["error"]


async def test_history_keeps_only_the_gist_of_long_replies(make_stack):
    long = " ".join(f"Sentence number {i} explains something about the board." for i in range(20))
    s = await make_stack([{"when": "explain", "calls": [{"name": "narrate", "arguments": {"segments": [
        {"text": long[i : i + 280]} for i in range(0, len(long), 280)]}}]}])  # fmt: skip
    await s.ui.send(type="user.message", text="explain")
    await _turn_done(s)
    reply = s.session.history[-1]["content"]
    assert len(reply) <= 300 and reply.endswith("…")


def test_speech_hints_prompt() -> None:
    from wysp_core.listen import MAX_PROMPT_CHARS, hint_prompt

    assert hint_prompt(["Cube", "cube", " Bevel ", "", "Edit Mode"]) == "Cube, Bevel, Edit Mode"
    assert len(hint_prompt([f"word{i}" for i in range(500)])) <= MAX_PROMPT_CHARS


async def test_one_narrate_call_builds_the_board_and_speaks(make_stack):
    """The whole answer in one model response: board (real entities + steps) and speech with cues."""
    s = await make_stack(
        [
            {"when": "how", "calls": [{"name": "narrate", "arguments": {
                "board": {"show": [CARDS[2]], "layout": "sequence", "concepts": [
                    {"label": "Drag the card", "kind": "step", "attach_to": CARDS[2], "key": "drag"},
                    {"label": "Drop it on Done", "kind": "step", "key": "drop"}]},
                "segments": [{"text": "Drag the card, then drop it.", "provenance": "illustrative",
                              "cues": [{"at_word": 0, "op": "focus", "target": "c:drag"}]}]}}]},
            {"after_tool": "narrate", "say": "EXTRA ROUND"},
        ]
    )  # fmt: skip
    await s.ui.send(type="user.message", text="how do I finish it?")
    await _turn_done(s)
    board = s.session.board
    assert any(n.ref == CARDS[2] and n.provenance == "observed" for n in board.nodes)
    assert board.node("c:drag") is not None and board.node("c:drop") is not None
    assert board.layout == "sequence"
    texts = [m["segment"]["text"] for m in s.ui.of_type("narration.segment")]
    assert texts == ["Drag the card, then drop it."], "one response, no extra round"
    seg = s.ui.of_type("narration.segment")[0]["segment"]
    await s.ui.send(type="narration.cue", segment_id=seg["id"], index=0)
    await s.ui.wait_for(lambda m: m.get("type") == "board.patch" and any(
        op.get("op") == "set_focus" and op.get("ids") == ["c:drag"] for op in m["patch"]["ops"]))  # fmt: skip


async def test_prop_patches_carry_complete_nodes(make_stack):
    """The Panel applies patches without the Core's models: a concept node must arrive with every field."""
    s = await make_stack([])
    result = await s.session.apply_board(
        [
            {
                "op": "add_node",
                "node": {"id": "c:s1", "ref": None, "kind": "step", "label": "Describe", "provenance": "illustrative"},
            }
        ]
    )
    assert result["ok"]
    patch = (
        await s.ui.wait_for(lambda m: m.get("type") == "board.patch" and m["patch"]["ops"][0]["op"] == "add_node")
    )["patch"]
    node = patch["ops"][0]["node"]
    assert node["props_view"] == [] and node["badges"] == [] and node["group"] is None
