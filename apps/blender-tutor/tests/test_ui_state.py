"""In-Blender Panel state, without Blender: board patches, narration pacing, layout."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from wysp_core.board.model import Board
from wysp_core.board.ops import BoardError, apply_ops

ADAPTER = Path(__file__).resolve().parents[1] / "adapter"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"wysp_test_{name}", ADAPTER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ui_state = _load("ui_state")
board_layout = _load("board_layout")

IDS = ["a", "b", "c", "d"]
PROV = st.sampled_from(["observed", "inferred", "illustrative"])


def _node(i: str, prov: str, order: int | None) -> dict:
    return {
        "id": i,
        "ref": None,
        "kind": "thing",
        "label": i.upper(),
        "provenance": prov,
        "confidence": 1.0,
        "props_view": [["k", "v"]],
        "group": None,
        "badges": [],
        "order": order,
    }


OPS = st.one_of(
    st.builds(
        lambda i, p, o: {"op": "add_node", "node": _node(i, p, o)},
        st.sampled_from(IDS),
        PROV,
        st.none() | st.integers(0, 5),
    ),
    st.builds(lambda i: {"op": "remove_node", "id": i}, st.sampled_from(IDS)),
    st.builds(
        lambda s, t, n: {
            "op": "add_edge",
            "edge": {"id": f"e{n}", "source": s, "target": t, "kind": "k", "label": None, "provenance": "observed"},
        },
        st.sampled_from(IDS),
        st.sampled_from(IDS),
        st.integers(0, 2),
    ),
    st.builds(lambda n: {"op": "remove_edge", "id": f"e{n}"}, st.integers(0, 2)),
    st.builds(lambda lay: {"op": "set_layout", "layout": lay}, st.sampled_from(["stack", "tree", "graph", "sequence"])),
    st.builds(lambda ids: {"op": "set_focus", "ids": ids}, st.lists(st.sampled_from(IDS), max_size=3)),
    st.builds(
        lambda t: {
            "op": "set_steps",
            "steps": [{"id": "s1", "index": 0, "text": "do it", "status": "active", "target": t}],
        },
        st.none() | st.sampled_from(IDS),
    ),
    st.builds(lambda s: {"op": "update_step", "id": "s1", "status": s}, st.sampled_from(["done", "failed"])),
    st.just({"op": "set_stale", "stale": True}),
    st.just({"op": "clear"}),
)


@settings(max_examples=150, deadline=None)
@given(st.lists(st.lists(OPS, min_size=1, max_size=4), min_size=1, max_size=6))
def test_prop_bld_p6_board_patches_match_core(patches: list[list[dict]]) -> None:
    """BLD-P6: applying the Core's patches in Blender yields exactly the Core's board."""
    core = Board()
    mirror = ui_state.empty_board()
    for ops in patches:
        try:
            nxt = apply_ops(core, ops)
        except BoardError:
            continue  # the Core rejects the patch and never sends it
        patch = {"base_version": core.version, "version": nxt.version, "ops": ops}
        mirror, why = ui_state.apply_patch(mirror, patch)
        assert why == "ok"
        core = nxt
    assert mirror == core.model_dump(mode="json")


def test_gap_asks_for_a_snapshot_and_duplicates_are_ignored() -> None:
    s = ui_state.UiState()
    out = s.handle({"type": "board.patch", "patch": {"base_version": 3, "version": 4, "ops": []}})
    assert out == [{"type": "board.snapshot_request"}]
    s.handle(
        {"type": "board.patch", "patch": {"base_version": 0, "version": 1, "ops": [{"op": "set_stale", "stale": True}]}}
    )
    assert s.board["stale"] and s.board["version"] == 1
    assert s.handle({"type": "board.patch", "patch": {"base_version": 0, "version": 1, "ops": []}}) == []


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _segment(text: str, cues: list[dict]) -> dict:
    return {
        "type": "narration.segment",
        "segment": {"id": "g1", "turn_id": "t", "index": 0, "text": text, "marker": None, "cues": cues},
    }


def test_silent_narration_fires_cues_then_reports_played() -> None:
    clock = Clock()
    s = ui_state.UiState(narrate=True, clock=clock)
    s.handle(
        _segment(
            "one two three four five six seven eight",
            [{"at_word": 0, "op": "highlight", "target": "x"}, {"at_word": 6, "op": "focus", "target": "y"}],
        )
    )
    assert s.tick() == [{"type": "narration.cue", "segment_id": "g1", "index": 0}]
    clock.t = 1.0
    assert s.tick() == []
    clock.t = 2.4
    assert s.tick() == [{"type": "narration.cue", "segment_id": "g1", "index": 1}]
    clock.t = 3.2
    assert s.tick() == [{"type": "narration.progress", "segment_id": "g1", "played": True}]
    assert s.transcript[-1]["state"] == "played"


def test_narration_off_only_records_the_text() -> None:
    s = ui_state.UiState(narrate=False)
    s.handle(_segment("hello", [{"at_word": 0, "op": "highlight", "target": "x"}]))
    assert s.tick() == []
    assert s.transcript[-1]["text"] == "hello"


def test_interrupt_cancels_pending_segments() -> None:
    s = ui_state.UiState(narrate=True, clock=Clock())
    s.handle(_segment("hello there", []))
    s.tick()
    assert s.interrupt() == {"type": "user.interrupt"}
    assert s.transcript[-1]["state"] == "cancelled"
    assert s.tick() == []


def test_permission_lifecycle() -> None:
    s = ui_state.UiState()
    s.handle({"type": "permission.request", "request_id": "r1", "title": "Add Bevel", "risk": "reversible"})
    assert s.permission["request_id"] == "r1"
    s.handle({"type": "permission.resolved", "request_id": "r1", "approved": True, "by": "click"})
    assert s.permission is None


def test_layout_is_deterministic_and_layered() -> None:
    board = ui_state.empty_board()
    board["nodes"] = [_node("a", "observed", None), _node("b", "observed", None), _node("c", "inferred", None)]
    board["edges"] = [{"id": "e1", "source": "a", "target": "b"}, {"id": "e2", "source": "b", "target": "c"}]
    pos = board_layout.layout(board)
    assert pos == board_layout.layout(board)
    assert pos["a"][0] < pos["b"][0] < pos["c"][0]
    board["layout"] = "stack"
    stack = board_layout.layout(board)
    assert stack["a"][1] > stack["b"][1] > stack["c"][1] and {x for x, _ in stack.values()} == {0.0}


def test_layout_survives_cycles() -> None:
    board = ui_state.empty_board()
    board["nodes"] = [_node("a", "observed", None), _node("b", "observed", None)]
    board["edges"] = [{"id": "e1", "source": "a", "target": "b"}, {"id": "e2", "source": "b", "target": "a"}]
    assert set(board_layout.layout(board)) == {"a", "b"}


class FakeVoice:
    """Stands in for ui_voice.VoicePlayer: audio is 'ready' once `deliver` is called."""

    def __init__(self) -> None:
        self.prepared: list[str] = []
        self.audio: dict[str, float | bool] = {}
        self.played: list[str] = []
        self.stopped = 0
        self.forgotten: list[str] = []
        self.playing = False

    def prepare(self, seg: dict) -> None:
        self.prepared.append(seg["id"])

    def deliver(self, sid: str, seconds: float | bool) -> None:
        self.audio[sid] = seconds

    def ready(self, sid: str):
        return self.audio.get(sid)

    def play(self, sid: str) -> bool:
        self.played.append(sid)
        self.playing = True
        return True

    def is_playing(self) -> bool:
        return self.playing

    def stop(self) -> None:
        self.stopped += 1
        self.playing = False

    def forget(self, sid: str) -> None:
        self.forgotten.append(sid)


def test_voiced_narration_waits_for_audio_and_follows_its_length() -> None:
    clock, voice = Clock(), FakeVoice()
    s = ui_state.UiState(narrate=True, clock=clock, voice=voice)
    s.handle(_segment("one two three four", [{"at_word": 2, "op": "highlight", "target": "x"}]))
    assert voice.prepared == ["g1"]
    assert s.tick() == []  # audio not there yet: wait
    voice.deliver("g1", 4.0)
    clock.t = 0.5
    assert s.tick() == [] and voice.played == ["g1"]
    clock.t = 2.6  # the cue is halfway through the words, so halfway through the 4 s of audio
    assert s.tick() == [{"type": "narration.cue", "segment_id": "g1", "index": 0}]
    clock.t = 4.6
    assert s.tick() == []  # audio still playing
    voice.playing = False
    assert s.tick() == [{"type": "narration.progress", "segment_id": "g1", "played": True}]
    assert voice.forgotten == ["g1"]


def test_voice_failure_falls_back_to_reading_pace() -> None:
    clock, voice = Clock(), FakeVoice()
    s = ui_state.UiState(narrate=True, clock=clock, voice=voice)
    s.handle(_segment("hello there", []))
    voice.deliver("g1", False)
    s.tick()
    assert voice.played == []
    clock.t = ui_state.MIN_SEGMENT_S + 0.1
    assert s.tick() == [{"type": "narration.progress", "segment_id": "g1", "played": True}]


def test_slow_voice_does_not_block_narration_forever() -> None:
    clock, voice = Clock(), FakeVoice()
    s = ui_state.UiState(narrate=True, clock=clock, voice=voice)
    s.handle(_segment("hello there", []))
    assert s.tick() == []
    clock.t = ui_state.VOICE_WAIT_S + 0.1
    s.tick()  # gives up waiting and shows it silently
    clock.t += ui_state.MIN_SEGMENT_S + 0.1
    assert s.tick()[-1]["type"] == "narration.progress"


def test_interrupt_stops_the_voice() -> None:
    clock, voice = Clock(), FakeVoice()
    s = ui_state.UiState(narrate=True, clock=clock, voice=voice)
    s.handle(_segment("hello there", []))
    voice.deliver("g1", 3.0)
    s.tick()
    s.interrupt()
    assert voice.stopped >= 1 and "g1" in voice.forgotten


def test_tts_url_follows_the_core_address() -> None:
    ui_voice = _load("ui_voice")
    assert ui_voice.tts_url("ws://127.0.0.1:8765/ws/adapter") == "http://127.0.0.1:8765/api/tts"
    assert ui_voice.tts_url("ws://localhost:8799/ws/adapter") == "http://localhost:8799/api/tts"


def test_sentences_appear_as_they_are_spoken() -> None:
    clock = Clock()
    s = ui_state.UiState(narrate=True, clock=clock)
    for i, text in enumerate(["First sentence here.", "Second one.", "Third one."]):
        seg = {"id": f"g{i}", "turn_id": "t", "index": i, "text": text, "marker": None, "cues": []}
        s.handle({"type": "narration.segment", "segment": seg})
    assert [t["text"] for t in s.visible_transcript()] == []  # nothing shown before it is spoken
    s.tick()
    assert [t["text"] for t in s.visible_transcript()] == ["First sentence here."]
    clock.t = 5.0
    s.tick()  # first finished
    s.tick()  # second starts
    assert [t["text"] for t in s.visible_transcript()] == ["First sentence here.", "Second one."]
    s.interrupt()  # second was playing: stays visible; third was never spoken: stays hidden
    assert [t["text"] for t in s.visible_transcript()] == ["First sentence here.", "Second one."]
    assert [t["state"] for t in s.transcript] == ["played", "cancelled", "skipped"]


def test_without_pacing_sentences_show_on_arrival() -> None:
    s = ui_state.UiState(narrate=False)
    s.handle(_segment("hello", []))
    assert [t["text"] for t in s.visible_transcript()] == ["hello"]


def test_spoken_yes_or_no_answers_a_pending_approval() -> None:
    s = ui_state.UiState()
    s.handle({"type": "permission.request", "request_id": "r1", "title": "Add a modifier", "risk": "reversible"})
    assert s.route_transcript("Yes, go ahead") == [
        {"type": "permission.respond", "request_id": "r1", "decision": "approve", "via": "voice"}
    ]
    assert s.route_transcript("no thanks")[0]["decision"] == "deny"
    out = s.route_transcript("what does a bevel do?")  # anything else is a question, even while waiting
    assert out == [{"type": "user.message", "text": "what does a bevel do?", "source": "voice"}]


def test_spoken_message_is_shown_and_sent_as_voice() -> None:
    s = ui_state.UiState()
    assert s.route_transcript("   ") == []
    assert s.route_transcript("add a cube") == [{"type": "user.message", "text": "add a cube", "source": "voice"}]
    assert s.transcript[-1] == {"kind": "user", "text": "add a cube", "source": "voice"}
