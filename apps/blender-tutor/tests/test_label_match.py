"""Label matching on OCR output recorded from real Blender 5.2 screenshots (no Blender, no OCR needed)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parent / "adapter"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"wysp_test_{name}", ADAPTER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


label_match = _load("label_match")
ui_targets = _load("ui_targets")
PROPS = json.loads((HERE / "fixtures" / "ocr_properties_modifiers.json").read_text(encoding="utf-8"))["lines"]
FULL = json.loads((HERE / "fixtures" / "ocr_full_window.json").read_text(encoding="utf-8"))["lines"]


def test_finds_a_button_inside_a_line_with_an_icon() -> None:
    m, ties = label_match.find("Add Modifier", PROPS)
    assert m is not None and m.score == 1.0 and ties == 1
    assert m.text == "Add Modifier"  # the "+" icon is not part of the box
    assert 110 <= m.x <= 140 and 100 <= m.y <= 120


def test_matches_labels_that_blender_truncated() -> None:
    m, _ = label_match.find("Levels", PROPS)
    assert m is not None and m.text.startswith("Level") and 0.8 <= m.score < 1.0
    t, _ = label_match.find("Thickness", PROPS)
    assert t is not None and t.text.startswith("Thic")


def test_picks_one_word_out_of_merged_header_labels() -> None:
    m, _ = label_match.find("Add", FULL)
    assert m is not None and m.text == "Add" and m.score == 1.0
    assert m.y < 80, "the Add menu of the 3D Viewport header, near the top of the window"
    o, _ = label_match.find("Object", FULL)
    assert o is not None and o.text == "Object" and o.x > m.x


def test_any_spelling_may_match() -> None:
    m, _ = label_match.find(["segments", "Mode"], PROPS)
    assert m is not None and m.text == "Mode"


def test_absent_label_is_not_invented() -> None:
    m, _ = label_match.find("Segments", PROPS)
    assert m is None
    visible = label_match.visible_labels(PROPS)
    assert "Add Modifier" in visible and "Render" in visible


def test_scores() -> None:
    assert label_match.score("Add Modifier", "+ Add Modifier") == 1.0
    assert label_match.score("Thickness", "Thic...") == 0.85
    assert label_match.score("Width", "Mode") == 0.0
    assert label_match.score("Subdivision", "Subdivisi0n") > 0.7  # an OCR misread


def test_label_refs_parse() -> None:
    t = ui_targets.parse("blender://ui/label/PROPERTIES/Add%20Modifier")
    assert t is not None and t.text == "Add Modifier" and t.area == "PROPERTIES"
    assert ui_targets.parse("blender://ui/label/VIEW_3D/Add").text == "Add"
    assert ui_targets.parse("blender://ui/label/NOPE/Add") is None
    assert ui_targets.parse("blender://ui/label/PROPERTIES/" + "x" * 80) is None


def test_wysp_own_chat_and_sidebar_are_never_matched() -> None:
    """Regression (session of 2026-11-10): "Bisect." was framed inside Wysp's own sidebar sentence."""
    lines = [
        {"text": "View Select Add Object", "words": [
            {"text": "View", "x": 250, "y": 51, "w": 38, "h": 12}, {"text": "Select", "x": 312, "y": 51, "w": 48, "h": 12},
            {"text": "Add", "x": 383, "y": 51, "w": 30, "h": 12}, {"text": "Object", "x": 437, "y": 51, "w": 50, "h": 12}]},
        {"text": "click Mesh, then Bisect.", "words": [
            {"text": "click", "x": 1300, "y": 600, "w": 30, "h": 12}, {"text": "Mesh,", "x": 1335, "y": 600, "w": 34, "h": 12},
            {"text": "then", "x": 1372, "y": 600, "w": 28, "h": 12}, {"text": "Bisect.", "x": 1404, "y": 600, "w": 44, "h": 12}]},
        {"text": "Wysp asks your approval: Add a modifier", "words": [
            {"text": "Wysp", "x": 30, "y": 800, "w": 40, "h": 12}, {"text": "Add", "x": 200, "y": 800, "w": 30, "h": 12}]},
    ]  # fmt: skip
    sidebar = [(1290, 120, 300, 700)]  # x, y, w, h of the 3D Viewport sidebar in the screenshot
    kept = label_match.without(lines, sidebar)
    assert label_match.find("Bisect", kept)[0] is None
    assert label_match.find("Mesh", kept)[0] is None
    add, ties = label_match.find("Add", kept)
    assert add is not None and add.y == 51 and ties == 1, "only the real Add menu, not the banner's text"
