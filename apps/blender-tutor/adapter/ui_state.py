"""What the in-Blender Panel shows: the Python twin of panel/src/store.ts. Pure Python, no bpy.

The Blender Panel is just another client of the Core's UI protocol (``/ws/ui``), exactly like the
browser Panel: it renders this state and sends protocol messages. No tutoring logic lives here.

``handle(msg)`` and ``tick(now)`` return the messages to send back (snapshot requests, narration
progress and cues), so the network layer stays dumb and this module is easy to test.
"""

from __future__ import annotations

import copy
import re
import time
from collections import deque
from typing import Any

MAX_TRANSCRIPT = 200
WORDS_PER_SECOND = 2.6  # reading pace used to time narration cues when no voice plays them
MIN_SEGMENT_S = 1.2
VOICE_WAIT_S = 8.0  # how long a segment waits for its audio before being shown silently


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


STATUS_TEXT = {
    "idle": "Ready",
    "thinking": "Thinking",
    "acting": "Acting",
    "speaking": "Speaking",
    "offline": "Offline",
}
PROVENANCE_MARKER = {"observed": "", "inferred": "likely ", "illustrative": "example: "}
MAX_DIAGRAM_ROWS = 24


def tail_start(line_counts: list[float], budget: float) -> int:
    """Index of the first item to show so that the newest items fit in `budget` lines.

    Blender panels cannot be scrolled from a script, so the chat shows only the newest items that fit and
    keeps the composer on screen. The newest item is always shown, even when it alone is longer than the budget.
    """
    used = 0
    start = len(line_counts)
    for i in range(len(line_counts) - 1, -1, -1):
        used += max(1, line_counts[i])
        if used > budget and start < len(line_counts):
            break
        start = i
    return start


def preview_lines(preview: Any, max_lines: int = 6, width: int = 44) -> list[str]:
    """A permission preview as short text lines: a text diff as is, a dict as ``key: value``, anything else as text."""
    if isinstance(preview, dict) and isinstance(preview.get("diff"), str):
        lines = preview["diff"].splitlines()
    elif isinstance(preview, dict):
        lines = [f"{k}: {v}" for k, v in preview.items()]
    elif isinstance(preview, (list, tuple)):
        lines = [str(v) for v in preview]
    else:
        lines = str(preview).splitlines() or [""]
    out = [line[:width] + ("…" if len(line) > width else "") for line in lines[:max_lines]]
    if len(lines) > max_lines:
        out.append(f"… {len(lines) - max_lines} more")
    return out


class UiState:
    def __init__(self, narrate: bool = True, clock=time.monotonic, voice=None) -> None:
        self.narrate = narrate  # time segments and fire their cues (when no browser voice does it)
        self.voice = voice  # optional VoicePlayer-like object: prepare / ready / play / is_playing / stop / forget
        self.voice_on = True  # the "Voice" switch in the menu; off means captions at reading pace
        self.view = "chat"  # "chat" or "board": one thing fills the panel at a time, like the browser Panel
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
        self._duration = 0.0
        self._waiting_since = 0.0
        self._pending_start = False

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
        self.clarification = None  # the user moved on: an old question must not linger (and be clicked later)
        self.view = "chat"  # sending a message goes back to the conversation, like the browser Panel
        self._touch()

    def node(self, node_id: str) -> dict[str, Any] | None:
        return next((n for n in self.board["nodes"] if n["id"] == node_id), None)

    def queued_segments(self) -> int:
        """Sentences received but not finished yet (playing or waiting)."""
        return len(self._queue) + (1 if self._current is not None else 0)

    def visible_transcript(self) -> list[dict[str, Any]]:
        """What the chat shows: Wysp's sentences appear as they are spoken, not all at once.

        Without narration pacing (another Panel speaks), sentences are shown as they arrive.
        """
        if not self.narrate:
            return list(self.transcript)
        return [t for t in self.transcript if not (t["kind"] == "wysp" and t["state"] in ("queued", "skipped"))]

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self.board["steps"]

    # ------------------------------------------------------- what the panel shows (same rules as Chat.tsx)
    @property
    def busy(self) -> bool:
        return self.connected and self.status != "idle"

    @property
    def has_cancelled(self) -> bool:
        return any(t["kind"] == "wysp" and t["state"] in ("cancelled", "skipped") for t in self.transcript)

    @property
    def show_stop(self) -> bool:
        return self.busy

    @property
    def show_continue(self) -> bool:
        """Only when something was cancelled and Wysp is not working."""
        return not self.busy and self.has_cancelled

    @property
    def has_diagram(self) -> bool:
        return bool(self.board["nodes"])

    @property
    def effective_view(self) -> str:
        return "board" if self.view == "board" and self.has_diagram else "chat"

    def set_view(self, view: str) -> None:
        if view in ("chat", "board") and view != self.view:
            self.view = view
            self._touch()

    @property
    def display_status(self) -> str:
        if not self.connected:
            return "offline"
        return self.status if self.status in STATUS_TEXT else "idle"

    @property
    def status_text(self) -> str:
        return STATUS_TEXT[self.display_status]

    @property
    def wait_text(self) -> str:
        """The dim line under the chat while Wysp works ("" when idle)."""
        if not self.busy:
            return ""
        if self.activity:
            return self.activity
        return {"thinking": "Thinking", "acting": "Working in Blender"}.get(self.status, "")

    @property
    def is_empty(self) -> bool:
        return not self.visible_transcript() and not self.clarification

    @property
    def active_app(self) -> dict[str, Any] | None:
        active = self.session.get("active_adapter")
        return next((a for a in self.adapters if a.get("adapter_id") == active), None)

    def app_label(self, adapter: dict[str, Any] | None) -> str:
        app = (adapter or {}).get("app") or {}
        return f"{app.get('name', '')} {app.get('version', '')}".strip() or str((adapter or {}).get("adapter_id", ""))

    def diagram_rows(self, limit: int = MAX_DIAGRAM_ROWS) -> tuple[list[dict[str, Any]], int]:
        """The board as a compact list: (rows, hidden_count). Provenance is spelled out like in the node tree."""
        labels = {n["id"]: n.get("label", "") for n in self.board["nodes"]}
        out_edges: dict[str, list[str]] = {}
        for e in self.board["edges"]:
            out_edges.setdefault(e["source"], []).append(labels.get(e["target"], ""))
        focus = set(self.board["focus"])
        rows = []
        for n in self.board["nodes"][:limit]:
            prov = n.get("provenance", "inferred")
            rows.append(
                {
                    "id": n["id"],
                    "text": f"{PROVENANCE_MARKER.get(prov, '')}{n.get('label', '')}",
                    "kind": n.get("kind", ""),
                    "provenance": prov,
                    "can_show": bool(n.get("ref")) and prov == "observed",
                    "focused": n["id"] in focus,
                    "links": [t for t in out_edges.get(n["id"], []) if t],
                }
            )
        return rows, max(0, len(self.board["nodes"]) - limit)

    def _voice(self):
        return self.voice if self.voice_on else None

    def set_voice(self, on: bool) -> None:
        self.voice_on = on
        if not on and self.voice is not None:
            self.voice.stop()
        self._touch()

    def set_connected(self, connected: bool) -> None:
        self.connected = connected
        if not connected:
            self.status = "idle"
            self._queue.clear()
            self._current = None
        self._touch()

    # ------------------------------------------------------------------- inbound
    def handle(self, m: dict[str, Any]) -> list[dict[str, Any]]:
        """Apply one Core message. Unknown or new message types (for example ``explore.state``) are ignored."""
        out: list[dict[str, Any]] = []
        if not isinstance(m, dict):
            return out
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
            self.clarification = None
        elif t == "board.snapshot":
            before = len(self.board["nodes"])
            self.board = copy.deepcopy(m["board"])
            if len(self.board["nodes"]) > before:
                self.view = "board"  # new elements appeared: show them, like the browser Panel
            self._touch(board=True)
        elif t == "board.patch":
            nxt, why = apply_patch(self.board, m["patch"])
            if nxt is not None:
                if len(nxt["nodes"]) > len(self.board["nodes"]):
                    self.view = "board"
                self.board = nxt
                self._touch(board=True)
            elif why == "gap":
                out.append({"type": "board.snapshot_request"})
        elif t == "narration.segment":
            seg = m["segment"]
            self.transcript.append({"kind": "wysp", "segment": seg, "text": seg.get("text", ""), "state": "queued"})
            if self.narrate:
                self._queue.append(seg)
                if self._voice() is not None:
                    self.voice.prepare(seg)
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
                # Cancelled while being spoken stays visible; never spoken is "skipped" and stays hidden.
                item["state"] = "cancelled" if item["state"] == "playing" else "skipped"
        dropped = [s for s in self._queue if cut(s)]
        self._queue = deque(s for s in self._queue if not cut(s))
        if self._current is not None and cut(self._current):
            dropped.append(self._current)
            self._current = None
            if self.voice is not None:
                self.voice.stop()
        if self.voice is not None:
            for seg in dropped:
                self.voice.forget(seg["id"])
        self._touch()

    @staticmethod
    def segment_duration(seg: dict[str, Any]) -> float:
        words = len(str(seg.get("text", "")).split())
        return max(MIN_SEGMENT_S, words / WORDS_PER_SECOND)

    def _start_segment(self, seg: dict[str, Any], now: float) -> bool:
        """Begin a segment. Returns False while its audio is still being fetched."""
        duration = None
        voice = self._voice()
        if voice is not None:
            ready = voice.ready(seg["id"])
            if ready is None and now - self._waiting_since < VOICE_WAIT_S:
                return False  # audio on its way: wait a little rather than speak out of sync
            if isinstance(ready, (int, float)) and not isinstance(ready, bool) and voice.play(seg["id"]):
                duration = float(ready)
        self._duration = duration if duration is not None else self.segment_duration(seg)
        self._started, self._cues_sent = now, 0
        self._mark(seg["id"], "playing")
        self._touch()
        return True

    def tick(self) -> list[dict[str, Any]]:
        """Advance narration (voiced or silent): fire due cues, then report the segment as played."""
        out: list[dict[str, Any]] = []
        now = self.clock()
        if self._current is None:
            if not self._queue:
                return out
            self._current = self._queue.popleft()
            self._waiting_since = now
            self._pending_start = True
        seg = self._current
        if self._pending_start:
            if not self._start_segment(seg, now):
                return out
            self._pending_start = False
        elapsed = now - self._started
        cues = seg.get("cues", [])
        words = max(1, len(str(seg.get("text", "")).split()))
        while self._cues_sent < len(cues):
            at = min(cues[self._cues_sent].get("at_word", 0), words) / words * self._duration
            if elapsed < at:
                break
            out.append({"type": "narration.cue", "segment_id": seg["id"], "index": self._cues_sent})
            self._cues_sent += 1
        still_playing = self._voice() is not None and self.voice.is_playing() and elapsed < self._duration + 2.0
        if elapsed >= self._duration and not still_playing:
            while self._cues_sent < len(cues):  # never drop a cue, even on a short segment
                out.append({"type": "narration.cue", "segment_id": seg["id"], "index": self._cues_sent})
                self._cues_sent += 1
            out.append({"type": "narration.progress", "segment_id": seg["id"], "played": True})
            self._mark(seg["id"], "played")
            if self.voice is not None:
                self.voice.forget(seg["id"])
            self._current = None
            self._touch()
        return out

    # ------------------------------------------------------------------ outbound
    def interrupt(self) -> dict[str, Any]:
        self.cancel_narration()
        return {"type": "user.interrupt"}

    def route_transcript(self, text: str) -> list[dict[str, Any]]:
        """What a spoken sentence becomes, exactly like the browser Panel's voice input.

        While an approval is pending, "yes"/"go ahead" approves and "no"/"cancel" denies (by voice: the Core
        refuses voice for irreversible actions and says why). Anything else is a message to Wysp.
        """
        t = text.strip()
        if not t:
            return []
        perm = self.permission
        if perm:
            if _YES.match(t):
                return [
                    {
                        "type": "permission.respond",
                        "request_id": perm["request_id"],
                        "decision": "approve",
                        "via": "voice",
                    }
                ]
            if _NO.match(t):
                return [
                    {"type": "permission.respond", "request_id": perm["request_id"], "decision": "deny", "via": "voice"}
                ]
        self.cancel_narration()
        self.add_user(t, "voice")
        return [{"type": "user.message", "text": t[:4000], "source": "voice"}]


_YES = re.compile(r"^(yes|yeah|yep|ok|okay|approve|approved|go ahead|do it|sure|confirm)\b", re.IGNORECASE)
_NO = re.compile(r"^(no|nope|deny|cancel|stop|don't|do not|refuse)\b", re.IGNORECASE)
