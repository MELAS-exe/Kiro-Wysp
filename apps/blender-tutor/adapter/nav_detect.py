"""Find the icons of a vertical tab column (the Properties editor's tabs) on a screenshot. Pure Python.

Blender draws each tab as a light icon on the dark column background, so scanning rows for bright pixels
gives one run of rows per icon. This is the visual half of the hybrid: it follows any UI scale, monitor
DPI or theme, where a measured formula drifts.

Input: ``rows`` of luminance values (0..1), top row first, for the columns of the tab bar.
Output: ``(top, bottom)`` row ranges, top first, one per icon.
"""

from __future__ import annotations


def icon_runs(
    rows: list[list[float]], min_height: int = 6, merge_gap: int = 3, contrast: float = 0.22
) -> list[tuple[int, int]]:
    if not rows:
        return []
    # The background is the most common dark level; icons are clearly brighter than it.
    flat = sorted(v for row in rows for v in row)
    background = flat[len(flat) // 4]
    threshold = background + contrast
    lit = [sum(1 for v in row if v > threshold) >= max(2, len(row) // 10) for row in rows]
    runs: list[list[int]] = []
    for y, on in enumerate(lit):
        if not on:
            continue
        if runs and y - runs[-1][1] <= merge_gap + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    return [(a, b) for a, b in runs if b - a + 1 >= min_height]


def tab_boxes(runs: list[tuple[int, int]], count: int) -> list[tuple[int, int]] | None:
    """Square-ish boxes around icons, if the runs look like `count` tabs (or the first ones of them).

    Returns None when the picture is not trustworthy (more runs than tabs, or wildly uneven icon sizes),
    so the caller can fall back to its estimate.
    """
    if not runs or len(runs) > count:
        return None
    heights = sorted(b - a + 1 for a, b in runs)
    median = heights[(len(heights) - 1) // 2]  # lower median: one oversized run cannot become the reference
    if any(h > 2.2 * median for h in heights):
        return None  # something else (a highlight, a tooltip) merged with an icon
    pad = max(2, median // 3)
    return [(a - pad, b + pad) for a, b in runs]
