"""What the in-Blender Panel shows: the Python twin of panel/src/store.ts. Pure Python, no bpy.

The Blender Panel is just another client of the Core's UI protocol (``/ws/ui``), exactly like the
browser Panel: it renders this state and sends protocol messages. No tutoring logic lives here.

``handle(msg)`` and ``tick(now)`` return the messages to send back (snapshot requests, narration
progress and cues), so the network layer stays dumb and this module is easy to test.
"""

from __future__ import annotations

import copy
import time
from collections import deque
from typing import Any

MAX_TRANSCRIPT = 200
WORDS_PER_SECOND = 2.6  # reading pace used to time narration cues when no voice plays them
MIN_SEGMENT_S = 1.2


def empty_board() -> dict[str, Any]:
    return {
        "version": 0,
        "layout": "graph",
        "focus": [],
        "nodes": [],
        "edges": [],
        "steps": [],
        "annotations": [],
        "stale": False,
    }


def _apply_op(b: dict[str, Any], op: dict[str, Any]) -> None:
    kind = op.get("op")
    if kind == "add_node":
        node = op["node"]
        for i, n in enumerate(b["nodes"]):
            if n["id"] == node["id"]:
                b["nodes"][i] = node
                break
        else:
            b["nodes"].append(node)
    elif kind == "remove_node":
        nid = op["id"]
        b["nodes"] = [n for n in b["nodes"] if n["id"] != nid]
        b["edges"] = [e for e in b["edges"] if e["source"] != nid and e["target"] != nid]
        b["annotations"] = [a for a in b["annotations"] if a["target"] != nid]
        b["focus"] = [f for f in b["focus"] if f != nid]
        for s in b["steps"]:
            if s.get("target") == nid:
                s["target"] = None
    elif kind == "add_edge":
        edge = op["edge"]
        for i, e in enumerate(b["edges"]):
            if e["id"] == edge["id"]:
                b["edges"][i] = edge
                break
        else:
            b["edges"].append(edge)
    elif kind == "remove_edge":
        b["edges"] = [e for e in b["edges"] if e["id"] != op["id"]]
    elif kind == "set_layout":
        b["layout"] = op["layout"]
    elif kind == "set_focus":
        ids = {n["id"] for n in b["nodes"]}
        b["focus"] = [i for i in op["ids"] if i in ids]
    elif kind == "set_steps":
        b["steps"] = copy.deepcopy(op["steps"])
    elif kind == "update_step":
        for s in b["steps"]:
            if s["id"] == op["id"]:
                if op.get("status"):
                    s["status"] = op["status"]
                if op.get("text"):
                    s["text"] = op["text"]
    elif kind == "add_annotation":
        ann = op["annotation"]
        b["annotations"] = [a for a in b["annotations"] if a["id"] != ann["id"]] + [ann]
    elif kind == "remove_annotation":
        b["annotations"] = [a for a in b["annotations"] if a["id"] != op["id"]]
    elif kind == "set_stale":
        b["stale"] = bool(op["stale"])
    elif kind == "clear":
        b.update(nodes=[], edges=[], steps=[], annotations=[], focus=[])


def apply_patch(board: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Return (new_board, "ok") or (None, "gap" | "duplicate"). Never mutates `board`."""
    if patch["version"] <= board["version"]:
        return None, "duplicate"
    if patch["base_version"] != board["version"]:
        return None, "gap"
    nxt = copy.deepcopy(board)
    for op in patch["ops"]:
        _apply_op(nxt, op)
    nxt["version"] = patch["version"]
    return nxt, "ok"


class UiState:
    def __init__(self, narrate: bool = True, clock=time.monotonic) -> None:
        self.narrate = narrate  # time segments and fire their cues (when no browser voice does it)
        self.clock = clock
        self.connected = False
        self.session: dict[str, Any] = {}
        self.adapters: list[dict[str, Any]] = []
        self.board = empty_board()
        self.status = "idle"
        self.activity = ""
        self.transcript: deque[dict[str, Any]] = deque(maxlen=MAX_TRANSCRIPT)
        self.permission: dict[str, Any] | None = None
        self.clarification: dict[str, Any] | None = None
        self.revision = 0  # bumped on every visible change; the UI redraws when it moves
        self.board_revision = 0  # bumped when the board changes; the node editor rebuilds then
        self._queue: deque[dict[str, Any]] = deque()  # segments waiting to be "played"
        self._current: dict[str, Any] | None = None
        self._started = 0.0
        self._cues_sent = 0

    # ----------------------------------------------------------------------- helpers
    def _touch(self, board: bool = False) -> None:
        self.revision += 1
        if board:
            self.board_revision += 1

    def note(self, text: str, tone: str = "info") -> None:
        self.transcript.append({"kind": "note", "text": text, "tone": tone})
        self._touch()

    def add_user(self, text: str, source: str = "typed") -> None:
        self.transcript.append({"kind": "user", "text": text, "source": source})
        self._touch()

    def node(self, node_id: str) -> dict[str, Any] | None:
        return next((n for n in self.board["nodes"] if n["id"] == node_id), None)

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self.board["steps"]

    def set_connected(self, connected: bool) -> None:
        self.connected = connected
        if not connected:
            self.status = "idle"
            self._queue.clear()
            self._current = None
        self._touch()

    # ------------------------------------------------------------------- inbound
    def handle(self, m: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        t = m.get("type")
        if t == "session.state":
            self.session = {k: v for k, v in m.items() if k != "type"}
        elif t == "adapters.list":
            self.adapters = list(m.get("adapters", []))
        elif t == "status":
            self.status = m.get("state", "idle")
            if self.status == "idle":
                self.activity = ""
        elif t == "activity":
            self.activity = str(m.get("text", ""))
        elif t == "chat.user":
            last = self.transcript[-1] if self.transcript else None
            if not (last and last["kind"] == "user" and last["text"] == m.get("text")):
                self.transcript.append({"kind": "user", "text": m.get("text", ""), "source": m.get("source", "typed")})
        elif t == "board.snapshot":
            self.board = copy.deepcopy(m["board"])
            self._touch(board=True)
        elif t == "board.patch":
            nxt, why = apply_patch(self.board, m["patch"])
            if nxt is not None:
                self.board = nxt
                self._touch(board=True)
            elif why == "gap":
                out.append({"type": "board.snapshot_request"})
        elif t == "narration.segment":
            seg = m["segment"]
            self.transcript.append({"kind": "wysp", "segment": seg, "text": seg.get("text", ""), "state": "queued"})
            if self.narrate:
                self._queue.append(seg)
        elif t == "narration.cancel":
            self.cancel_narration(m.get("from_index"))
        elif t == "clarification":
            self.clarification = {"question": m.get("question", ""), "options": list(m.get("options", []))}
        elif t == "permission.request":
            self.permission = {k: v for k, v in m.items() if k != "type"}
        elif t == "permission.resolved":
            if self.permission and self.permission.get("request_id") == m.get("request_id"):
                self.permission = None
        elif t == "evidence.added":
            outcomes = (m.get("evidence") or {}).get("outcomes", [])
            ok = all(o.get("ok") for o in outcomes)
            self.transcript.append(
                {"kind": "evidence", "text": m.get("title", ""), "scope": m.get("scope", ""), "ok": ok}
            )
        elif t == "error":
            self.transcript.append({"kind": "note", "text": str(m.get("message", "")), "tone": "error"})
        else:
            return out
        self._touch()
        return out

    # ----------------------------------------------------------------- narration
    def _mark(self, seg_id: str, state: str) -> None:
        for item in self.transcript:
            if item["kind"] == "wysp" and item["segment"]["id"] == seg_id:
                item["state"] = state

    def cancel_narration(self, from_index: int | None = None) -> None:
        def cut(seg: dict[str, Any]) -> bool:
            return from_index is None or seg.get("index", 0) >= from_index

        for item in self.transcript:
            if item["kind"] == "wysp" and item["state"] in ("queued", "playing") and cut(item["segment"]):
                item["state"] = "cancelled"
        self._queue = deque(s for s in self._queue if not cut(s))
        if self._current is not None and cut(self._current):
            self._current = None
        self._touch()

    @staticmethod
    def segment_duration(seg: dict[str, Any]) -> float:
        words = len(str(seg.get("text", "")).split())
        return max(MIN_SEGMENT_S, words / WORDS_PER_SECOND)

    def tick(self) -> list[dict[str, Any]]:
        """Advance silent narration: fire due cues, then report the segment as played."""
        out: list[dict[str, Any]] = []
        now = self.clock()
        if self._current is None:
            if not self._queue:
                return out
            self._current = self._queue.popleft()
            self._started, self._cues_sent = now, 0
            self._mark(self._current["id"], "playing")
            self._touch()
        seg = self._current
        elapsed = now - self._started
        cues = seg.get("cues", [])
        while self._cues_sent < len(cues) and elapsed >= cues[self._cues_sent].get("at_word", 0) / WORDS_PER_SECOND:
            out.append({"type": "narration.cue", "segment_id": seg["id"], "index": self._cues_sent})
            self._cues_sent += 1
        if elapsed >= self.segment_duration(seg):
            while self._cues_sent < len(cues):  # never drop a cue, even on a short segment
                out.append({"type": "narration.cue", "segment_id": seg["id"], "index": self._cues_sent})
                self._cues_sent += 1
            out.append({"type": "narration.progress", "segment_id": seg["id"], "played": True})
            self._mark(seg["id"], "played")
            self._current = None
            self._touch()
        return out

    # ------------------------------------------------------------------ outbound
    def interrupt(self) -> dict[str, Any]:
        self.cancel_narration()
        return {"type": "user.interrupt"}
