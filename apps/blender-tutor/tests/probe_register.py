"""Probe: the add-on registers, builds a board tree, removes it before saving, and unregisters cleanly.

blender -b --factory-startup --python-use-system-env --python probe_register.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import run_adapter  # noqa: E402

pkg = run_adapter.load_adapter()
pkg.register()
from wysp_tutor import board_tree  # noqa: E402

board = {
    "version": 1,
    "layout": "stack",
    "focus": ["n:a"],
    "nodes": [
        {"id": "n:a", "ref": "blender://object/Cube", "kind": "object", "label": "Cube", "provenance": "observed",
         "confidence": 1.0, "props_view": [["type", "MESH"]], "group": None, "badges": [], "order": None},
        {"id": "c:1", "ref": None, "kind": "concept", "label": "Idea", "provenance": "illustrative",
         "confidence": 1.0, "props_view": [], "group": None, "badges": [], "order": None},
    ],
    "edges": [{"id": "e1", "source": "n:a", "target": "c:1", "kind": "explains", "label": None, "provenance": "inferred"}],
    "steps": [],
    "annotations": [{"id": "a1", "target": "n:a", "text": "the default cube", "provenance": "inferred"}],
    "stale": False,
}  # fmt: skip
board_tree.sync(board)
tree = board_tree.get_tree(create=False)
print(
    "PROBE tree nodes",
    len(tree.nodes),
    "links",
    len(tree.links),
    "focus color",
    tuple(round(c, 2) for c in tree.nodes[0].color),
)
print("PROBE lines", tree.nodes[0].lines.split("\n"))
with tempfile.TemporaryDirectory() as d:
    path = str(Path(d) / "saved.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    print("PROBE tree after save", bpy.data.node_groups.get(board_tree.TREE_NAME) is not None)
    with bpy.data.libraries.load(path) as (src, _dst):
        print("PROBE groups in saved file", list(src.node_groups))
pkg.unregister()
print("PROBE unregistered", not hasattr(bpy.types, "WyspBoardNode"))
