"""Find a label in OCR output: which words on a screenshot are the button, menu or field we want?

Pure Python (no bpy), so it can be tested on recorded OCR results. Input lines are the Core's
``/api/ocr`` format: ``{"text", "words": [{"text", "x", "y", "w", "h"}]}`` in image pixels, origin top-left.

Blender specifics handled here:
* labels truncated to fit their column (``Thic...`` for ``Thickness``, ``Level…`` for ``Levels``);
* several labels in one OCR line (``Add Object Global v``): any run of consecutive words can match;
* menu arrows and icons read as stray characters (``v``, ``>``, ``+``, ``•``).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

_ELLIPSIS = re.compile(r"(\.\.\.|…)$")
_JUNK = re.compile(r"^[^\w]+|[^\w…]+$")


def norm(text: str) -> str:
    text = text.replace("...", "…").casefold()
    words = [_JUNK.sub("", w) for w in text.split()]
    return " ".join(w for w in words if w)


@dataclass
class Match:
    text: str  # what was read on screen
    score: float
    x: float
    y: float
    w: float
    h: float

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "score": round(self.score, 2), "x": self.x, "y": self.y, "w": self.w, "h": self.h}


def score(wanted: str, seen: str) -> float:
    """1.0 for the same label, ~0.85 for a truncated one, a fuzzy ratio for OCR misreads, else 0."""
    a, b = norm(wanted), norm(seen)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if b.endswith("…"):
        stem = b[:-1].rstrip()
        if len(stem) >= 3 and a.startswith(stem):
            return 0.85
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return round(ratio * 0.9, 3) if ratio >= 0.8 else 0.0


def _groups(words: list[dict[str, Any]]) -> list[int]:
    """Group id per word: a horizontal gap wider than ~0.9 text heights starts a new label.

    OCR joins neighbouring menus into one line (``Add Object Global``), but the gap between two labels is much
    wider than the space between two words of one label (``Object Mode``).
    """
    ids, gid = [], 0
    for k, w in enumerate(words):
        if k:
            prev = words[k - 1]
            gap = w["x"] - (prev["x"] + prev["w"])
            if gap > 0.9 * max(w["h"], prev["h"], 1):
                gid += 1
        ids.append(gid)
    return ids


def find(wanted: str | list[str], lines: list[dict[str, Any]], min_score: float = 0.7) -> tuple[Match | None, int]:
    """Best match for the label (or any of several spellings) and how many places matched equally well."""
    names = [wanted] if isinstance(wanted, str) else list(wanted)
    best: Match | None = None
    ties = 0
    for line in lines:
        # Icons read as symbols ("+", ">", "v") never belong to a label's box.
        words = [w for w in line.get("words", []) if norm(str(w.get("text", ""))) not in ("", "v")]
        gids = _groups(words)
        for i in range(len(words)):
            for j in range(i, min(len(words), i + 6)):
                span = words[i : j + 1]
                seen = " ".join(str(w["text"]) for w in span)
                s = max(score(n, seen) for n in names)
                if s < min_score:
                    continue
                whole = (i == 0 or gids[i - 1] != gids[i]) and (j == len(words) - 1 or gids[j + 1] != gids[j])
                if not whole:
                    s *= 0.95  # part of a longer label ("Object" in "Object Mode"): prefer a label on its own
                x0 = min(w["x"] for w in span)
                y0 = min(w["y"] for w in span)
                x1 = max(w["x"] + w["w"] for w in span)
                y1 = max(w["y"] + w["h"] for w in span)
                m = Match(seen, s, x0, y0, x1 - x0, y1 - y0)
                if best is None or s > best.score + 1e-6:
                    best, ties = m, 1
                elif abs(s - best.score) <= 1e-6 and (m.x, m.y) != (best.x, best.y):
                    ties += 1  # same label in another place: the first in reading order wins
    return best, ties


def visible_labels(lines: list[dict[str, Any]], limit: int = 30) -> list[str]:
    """Readable labels on the screenshot, for telling the tutor what it could point at instead."""
    out: list[str] = []
    for line in lines:
        text = " ".join(_JUNK.sub("", str(w.get("text", ""))) for w in line.get("words", [])).strip()
        if len(text) >= 3 and any(ch.isalpha() for ch in text) and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


# Text Wysp itself puts on screen (its sidebar chat, banners, callouts): never a target.
OWN_TEXT = ("wysp", "listening", "look for", "asks your approval", "understanding what you said", "newest first")


def without(lines: list[dict[str, Any]], rects: list[tuple[float, float, float, float]]) -> list[dict[str, Any]]:
    """Drop words inside `rects` (image pixels, origin top-left) and lines showing Wysp's own text.

    The 3D Viewport screenshot includes its sidebar, where Wysp's chat repeats the very words it is pointing
    at ("click Mesh, then Bisect"): matching there would frame Wysp's own sentence instead of the button.
    """
    out = []
    for line in lines:
        if any(p in str(line.get("text", "")).casefold() for p in OWN_TEXT):
            continue
        words = []
        for w in line.get("words", []):
            cx, cy = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
            if not any(x <= cx <= x + rw and y <= cy <= y + rh for x, y, rw, rh in rects):
                words.append(w)
        if words:
            out.append({"text": " ".join(str(w["text"]) for w in words), "words": words})
    return out
