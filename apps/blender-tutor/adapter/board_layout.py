"""Deterministic board layout for the node editor. Pure Python, no bpy.

Mirrors the Panel's layouts: ``stack`` (one ordered column), ``sequence`` (one ordered row),
``tree`` / ``graph`` (layered: each node one column right of the node that points to it).
Returns node-editor coordinates (y grows upwards, so rows go down with negative y).
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

NODE_WIDTH = 240.0
COL_GAP = 90.0
ROW_GAP = 40.0
BASE_HEIGHT = 70.0
LINE_HEIGHT = 22.0


def node_height(node: dict[str, Any], annotations: int = 0) -> float:
    return BASE_HEIGHT + LINE_HEIGHT * (len(node.get("props_view", [])) + annotations + 1)


def _ordered(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Unordered nodes (a container such as an object) first, then by `order`, then examples last."""
    indexed = list(enumerate(nodes))
    indexed.sort(
        key=lambda p: (
            p[1].get("provenance") == "illustrative",
            p[1].get("order") is not None,
            p[1].get("order") or 0,
            p[0],
        )
    )
    return [n for _, n in indexed]


def layered_depths(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, int]:
    """Breadth-first depth from the roots (nodes nothing points to). Cycles and islands get depth 0."""
    ids = [n["id"] for n in nodes]
    known = set(ids)
    out: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, int] = defaultdict(int)
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in known and t in known and s != t:
            out[s].append(t)
            incoming[t] += 1
    depth: dict[str, int] = {}
    for root in [i for i in ids if incoming[i] == 0] + ids:  # roots first, then anything left (cycles)
        if root in depth:
            continue
        depth[root] = 0
        q = deque([root])
        while q:
            cur = q.popleft()
            for nxt in out[cur]:
                if nxt not in depth:
                    depth[nxt] = depth[cur] + 1
                    q.append(nxt)
    return depth


def layout(board: dict[str, Any]) -> dict[str, tuple[float, float]]:
    nodes = board.get("nodes", [])
    notes: dict[str, int] = defaultdict(int)
    for a in board.get("annotations", []):
        notes[a.get("target")] += 1
    kind = board.get("layout", "graph")
    pos: dict[str, tuple[float, float]] = {}
    if kind == "stack":
        y = 0.0
        for n in _ordered(nodes):
            pos[n["id"]] = (0.0, y)
            y -= node_height(n, notes[n["id"]]) + ROW_GAP
        return pos
    if kind == "sequence":
        for i, n in enumerate(_ordered(nodes)):
            pos[n["id"]] = (i * (NODE_WIDTH + COL_GAP), 0.0)
        return pos
    depth = layered_depths(nodes, board.get("edges", []))
    column_y: dict[int, float] = defaultdict(float)
    for n in _ordered(nodes):
        d = depth.get(n["id"], 0)
        pos[n["id"]] = (d * (NODE_WIDTH + COL_GAP), column_y[d])
        column_y[d] -= node_height(n, notes[n["id"]]) + ROW_GAP
    return pos
