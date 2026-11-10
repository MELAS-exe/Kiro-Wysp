"""Tab icon detection on synthetic tab columns (the screenshot side is checked in a GUI Blender)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1] / "adapter"
_spec = importlib.util.spec_from_file_location("wysp_test_nav_detect", ADAPTER / "nav_detect.py")
nav_detect = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = nav_detect
_spec.loader.exec_module(nav_detect)

BG, ICON, WIDTH = 0.12, 0.8, 16


def column(icons: list[tuple[int, int]], height: int = 400, active: tuple[int, int] | None = None) -> list[list[float]]:
    rows = [[BG] * WIDTH for _ in range(height)]
    if active:
        for y in range(*active):
            rows[y] = [0.28] * WIDTH  # the active tab's lighter button, below the icon threshold
    for top, bottom in icons:
        for y in range(top, bottom):
            rows[y] = [BG] * 3 + [ICON] * (WIDTH - 6) + [BG] * 3
    return rows


def test_one_run_per_icon_in_order() -> None:
    icons = [(10, 30), (50, 70), (90, 110), (140, 160)]  # a wider gap before the 4th: a new tab group
    runs = nav_detect.icon_runs(column(icons))
    assert runs == [(a, b - 1) for a, b in icons]
    boxes = nav_detect.tab_boxes(runs, 4)
    assert boxes is not None and len(boxes) == 4 and boxes[0][0] < 10 and boxes[0][1] > 29


def test_scales_with_any_icon_size() -> None:
    small = nav_detect.icon_runs(column([(10, 22), (40, 52)]))
    large = nav_detect.icon_runs(column([(10, 45), (70, 105)]))
    assert len(small) == 2 and len(large) == 2


def test_active_tab_background_is_not_an_icon() -> None:
    runs = nav_detect.icon_runs(column([(10, 30), (50, 70)], active=(45, 75)))
    assert runs == [(10, 29), (50, 69)]


def test_untrustworthy_pictures_fall_back() -> None:
    runs = nav_detect.icon_runs(column([(10, 30), (50, 70), (90, 110)]))
    assert nav_detect.tab_boxes(runs, 2) is None  # more icons than tabs: something else is there
    merged = nav_detect.icon_runs(column([(10, 30), (50, 130)]))
    assert nav_detect.tab_boxes(merged, 5) is None  # one run far taller than the others
    assert nav_detect.tab_boxes([], 3) is None
