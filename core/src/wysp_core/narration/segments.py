"""Narration segments: short pieces of speech/captions with cues, plus interruption and resume."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

MAX_SEGMENT_CHARS = 300
MARKERS = {"inferred": "likely", "illustrative": "for example"}


@dataclass
class Segment:
    id: str
    turn_id: str
    index: int
    text: str
    provenance: str = "observed"
    cues: list[dict[str, Any]] = field(default_factory=list)

    def to_message(self) -> dict[str, Any]:
        return {
            "type": "narration.segment",
            "segment": {
                "id": self.id,
                "turn_id": self.turn_id,
                "index": self.index,
                "text": self.text,
                "marker": MARKERS.get(self.provenance),
                "cues": self.cues,
            },
        }


def clean_text(text: str) -> str:
    """Narration is spoken: strip the Markdown that chat models like to add (bold, code, bullets, headings)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"(\*\*|__|`)", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", "", text)
    text = re.sub(r"(?m)^\s*#+\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)
    return text


def split_text(text: str, limit: int = MAX_SEGMENT_CHARS) -> list[str]:
    """Split on sentence boundaries and pack sentences into chunks of at most `limit` characters."""
    text = re.sub(r"\s+", " ", clean_text(text)).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    chunks: list[str] = []
    current = ""
    for s in sentences:
        while len(s) > limit:  # a single very long sentence: cut at the last space
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(s[:cut].strip())
            s = s[cut:].strip()
        if current and len(current) + 1 + len(s) > limit:
            chunks.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


class NarrationState:
    """Tracks which segments of which turn were published and played, for interrupt and resume."""

    def __init__(self) -> None:
        self.turn_id: str | None = None
        self.segments: list[Segment] = []
        self.played: set[str] = set()
        self._next_index = 0
        self.interrupted: list[Segment] = []  # unplayed segments of the last interrupted turn

    def new_turn(self) -> str:
        self.turn_id = uuid.uuid4().hex[:8]
        self.segments = []
        self.played = set()
        self._next_index = 0
        self.interrupted = []
        return self.turn_id

    def add(self, text: str, provenance: str = "observed", cues: list[dict[str, Any]] | None = None) -> list[Segment]:
        assert self.turn_id is not None, "call new_turn() first"
        out = []
        chunks = split_text(text)
        for i, chunk in enumerate(chunks):
            seg = Segment(
                id=uuid.uuid4().hex[:8],
                turn_id=self.turn_id,
                index=self._next_index,
                text=chunk,
                provenance=provenance,
                cues=(cues or []) if i == 0 else [],
            )
            self._next_index += 1
            self.segments.append(seg)
            out.append(seg)
        return out

    def mark_played(self, segment_id: str) -> None:
        self.played.add(segment_id)

    def interrupt(self) -> int:
        """Remember what was not played. Returns the index of the first unplayed segment."""
        self.interrupted = [s for s in self.segments if s.id not in self.played]
        return self.interrupted[0].index if self.interrupted else self._next_index

    def resume(self) -> list[Segment]:
        pending, self.interrupted = self.interrupted, []
        return pending

    def find(self, segment_id: str) -> Segment | None:
        return next((s for s in self.segments if s.id == segment_id), None)
