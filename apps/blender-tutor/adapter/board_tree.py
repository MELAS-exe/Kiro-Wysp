"""The Wysp board inside Blender: a custom node tree shown in a Node Editor.

The tree is a *view*: it is rebuilt from ``UiState.board`` (which the Core sends) whenever the board
changes, and never feeds anything back except two user gestures, forwarded as UI protocol messages:
selecting a node (``board.select``) and asking "Why?" (``board.ask_why``).

Provenance looks the same as in the browser Panel: observed nodes are solid teal, inferred nodes are
dimmer and say "likely", illustrative nodes are grey and tagged "example".

The tree is named ``.Wysp Board`` (hidden from most lists) and is removed before a file is saved, so
.blend files never depend on the add-on.
"""

from __future__ import annotations

import logging

import bpy
from bpy.props import StringProperty
from bpy.types import Node, NodeSocket, NodeTree, Operator

from .board_layout import NODE_WIDTH, layout

log = logging.getLogger("wysp.blender.ui")

TREE_TYPE = "WyspBoardTreeType"
TREE_NAME = ".Wysp Board"

COLORS = {
    "observed": (0.05, 0.24, 0.22),
    "inferred": (0.15, 0.18, 0.25),
    "illustrative": (0.22, 0.22, 0.22),
}
FOCUS_COLOR = (0.08, 0.45, 0.40)
MARKERS = {"observed": "", "inferred": "likely ", "illustrative": "example: "}


class WyspBoardTree(NodeTree):
    """Wysp board: what the tutor is explaining, built from the scene"""

    bl_idname = TREE_TYPE
    bl_label = "Wysp Board"
    bl_icon = "LIGHT_SUN"


class WyspBoardSocket(NodeSocket):
    bl_idname = "WyspBoardSocket"
    bl_label = "Link"

    def draw(self, context, layout, node, text):
        layout.label(text="")

    def draw_color(self, context, node):
        return (0.18, 0.83, 0.75, 1.0)


class WyspBoardNode(Node):
    """A board node (read-only view)"""

    bl_idname = "WyspBoardNode"
    bl_label = "Wysp"
    bl_width_default = NODE_WIDTH

    wysp_id: StringProperty()  # type: ignore[valid-type]
    wysp_ref: StringProperty()  # type: ignore[valid-type]
    provenance: StringProperty(default="observed")  # type: ignore[valid-type]
    lines: StringProperty()  # type: ignore[valid-type]  # "\n"-joined detail lines

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == TREE_TYPE

    def init(self, context):
        self.inputs.new("WyspBoardSocket", "")
        self.outputs.new("WyspBoardSocket", "")

    def draw_buttons(self, context, layout):
        col = layout.column(align=True)
        if self.provenance == "observed":
            col.label(text="observed in Blender", icon="HIDE_OFF")
        elif self.provenance == "inferred":
            col.label(text="inferred (likely)", icon="QUESTION")
        else:
            col.label(text="example, not your scene", icon="INFO")
        for line in self.lines.split("\n") if self.lines else []:
            col.label(text=line)
        row = layout.row(align=True)
        op = row.operator("wysp.board_why", text="Why?", icon="QUESTION")
        op.node_id = self.wysp_id
        if self.wysp_ref and self.provenance == "observed":
            op2 = row.operator("wysp.board_show", text="Show", icon="RESTRICT_SELECT_OFF")
            op2.node_id = self.wysp_id


# ------------------------------------------------------------------------------- sync
def get_tree(create: bool = True):
    tree = bpy.data.node_groups.get(TREE_NAME)
    if tree is None and create:
        tree = bpy.data.node_groups.new(TREE_NAME, TREE_TYPE)
        tree.use_fake_user = False
    return tree


def _lines(node: dict, notes: list[str]) -> str:
    out = [f"{k}: {v}"[:44] for k, v in node.get("props_view", [])[:6]]
    out += [f"badge: {b}"[:44] for b in node.get("badges", [])[:3]]
    out += [f"note: {t}"[:44] for t in notes]
    return "\n".join(out)


def sync(board: dict) -> None:
    """Rebuild the node tree from a board (at most 60 nodes, so a rebuild is cheap)."""
    tree = get_tree()
    tree.nodes.clear()
    notes: dict[str, list[str]] = {}
    for a in board.get("annotations", []):
        notes.setdefault(a.get("target"), []).append(str(a.get("text", "")))
    focus = set(board.get("focus", []))
    pos = layout(board)
    by_id = {}
    for n in board.get("nodes", []):
        node = tree.nodes.new("WyspBoardNode")
        prov = n.get("provenance", "inferred")
        node.wysp_id = n["id"]
        node.wysp_ref = n.get("ref") or ""
        node.provenance = prov
        node.label = (MARKERS.get(prov, "") + f"{n.get('label', '')}  ({n.get('kind', '')})")[:60]
        node.lines = _lines(n, notes.get(n["id"], []))
        node.use_custom_color = True
        node.color = FOCUS_COLOR if n["id"] in focus else COLORS.get(prov, COLORS["inferred"])
        node.width = NODE_WIDTH
        node.location = pos.get(n["id"], (0.0, 0.0))
        node.select = n["id"] in focus
        by_id[n["id"]] = node
    for e in board.get("edges", []):
        src, dst = by_id.get(e.get("source")), by_id.get(e.get("target"))
        if src is not None and dst is not None:
            tree.links.new(src.outputs[0], dst.inputs[0])
    for area in _board_areas():
        area.tag_redraw()


def active_node_id() -> str | None:
    tree = get_tree(create=False)
    node = tree.nodes.active if tree is not None else None
    return getattr(node, "wysp_id", None) or None


def _board_areas():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "NODE_EDITOR" and area.ui_type == TREE_TYPE:
                yield area


def show_in_area(area) -> None:
    area.ui_type = TREE_TYPE
    space = area.spaces.active
    space.node_tree = get_tree()
    try:
        space.show_region_ui = True
    except AttributeError:
        pass


def open_window(context) -> bool:
    """Open the board in a new window (falls back to turning the Timeline into the board)."""
    before = set(context.window_manager.windows)
    try:
        bpy.ops.wm.window_new()
    except RuntimeError as exc:
        log.warning("cannot open a window for the board: %s", exc)
    new = [w for w in context.window_manager.windows if w not in before]
    if new:
        win = new[0]
        area = max(win.screen.areas, key=lambda a: a.width * a.height)
        show_in_area(area)
        return True
    for area in context.screen.areas:
        if area.ui_type in ("TIMELINE", "DOPESHEET"):
            show_in_area(area)
            return True
    return False


def remove_tree() -> None:
    tree = get_tree(create=False)
    if tree is not None:
        bpy.data.node_groups.remove(tree)


# --------------------------------------------------------------------------- operators
class WYSP_OT_board_open(Operator):
    bl_idname = "wysp.board_open"
    bl_label = "Open Board"
    bl_description = "Show the Wysp board in a new window"

    def execute(self, context):
        if not open_window(context):
            self.report({"WARNING"}, "Could not open the board")
            return {"CANCELLED"}
        return {"FINISHED"}


class WYSP_OT_board_here(Operator):
    bl_idname = "wysp.board_here"
    bl_label = "Board in Timeline"
    bl_description = "Turn the Timeline area into the Wysp board"

    def execute(self, context):
        for area in context.screen.areas:
            if area.ui_type in ("TIMELINE", "DOPESHEET", TREE_TYPE):
                show_in_area(area)
                return {"FINISHED"}
        self.report({"WARNING"}, "No Timeline area in this layout")
        return {"CANCELLED"}


CLASSES = (WyspBoardTree, WyspBoardSocket, WyspBoardNode, WYSP_OT_board_open, WYSP_OT_board_here)
