"""Board operations. `apply_ops` is a pure function mirrored in TypeScript by the Panel.

Operations (plain dicts, the wire format):
  {"op": "add_node", "node": {...}}            upsert by id
  {"op": "remove_node", "id": "..."}           also removes its edges, annotations and steps' target
  {"op": "add_edge", "edge": {...}}            upsert by id
  {"op": "remove_edge", "id": "..."}
  {"op": "set_layout", "layout": "stack"}
  {"op": "set_focus", "ids": ["..."]}
  {"op": "set_steps", "steps": [...]}          replaces all steps
  {"op": "update_step", "id": "...", "status": "done"}
  {"op": "add_annotation", "annotation": {...}}
  {"op": "remove_annotation", "id": "..."}
  {"op": "set_stale", "stale": true}
  {"op": "clear"}
"""

from __future__ import annotations

from typing import Any

from .model import MAX_NODES, Annotation, Board, BoardEdge, BoardNode, BoardPatch, Step


class BoardError(ValueError):
    pass


def apply_op(board: Board, op: dict[str, Any]) -> None:
    kind = op.get("op")
    if kind == "add_node":
        node = BoardNode.model_validate(op["node"])
        for i, existing in enumerate(board.nodes):
            if existing.id == node.id:
                board.nodes[i] = node
                break
        else:
            if len(board.nodes) >= MAX_NODES:
                raise BoardError(f"the board is full ({MAX_NODES} nodes): remove nodes or clear it first")
            board.nodes.append(node)
    elif kind == "remove_node":
        nid = op["id"]
        board.nodes = [n for n in board.nodes if n.id != nid]
        board.edges = [e for e in board.edges if e.source != nid and e.target != nid]
        board.annotations = [a for a in board.annotations if a.target != nid]
        board.focus = [f for f in board.focus if f != nid]
        for s in board.steps:
            if s.target == nid:
                s.target = None
    elif kind == "add_edge":
        edge = BoardEdge.model_validate(op["edge"])
        ids = {n.id for n in board.nodes}
        if edge.source not in ids or edge.target not in ids:
            raise BoardError(f"edge {edge.id} references a node that is not on the board")
        for i, existing in enumerate(board.edges):
            if existing.id == edge.id:
                board.edges[i] = edge
                break
        else:
            board.edges.append(edge)
    elif kind == "remove_edge":
        board.edges = [e for e in board.edges if e.id != op["id"]]
    elif kind == "set_layout":
        board.layout = op["layout"]
    elif kind == "set_focus":
        ids = {n.id for n in board.nodes}
        board.focus = [i for i in op["ids"] if i in ids]
    elif kind == "set_steps":
        board.steps = [Step.model_validate(s) for s in op["steps"]]
    elif kind == "update_step":
        for s in board.steps:
            if s.id == op["id"]:
                if "status" in op:
                    s.status = op["status"]
                if "text" in op:
                    s.text = op["text"]
    elif kind == "add_annotation":
        ann = Annotation.model_validate(op["annotation"])
        if board.node(ann.target) is None:
            raise BoardError(f"annotation target {ann.target} is not on the board")
        board.annotations = [a for a in board.annotations if a.id != ann.id] + [ann]
    elif kind == "remove_annotation":
        board.annotations = [a for a in board.annotations if a.id != op["id"]]
    elif kind == "set_stale":
        board.stale = bool(op["stale"])
    elif kind == "clear":
        board.nodes, board.edges, board.steps, board.annotations, board.focus = [], [], [], [], []
    else:
        raise BoardError(f"unknown board op {kind!r}")


def apply_ops(board: Board, ops: list[dict[str, Any]]) -> Board:
    """Apply ops in order and bump the version once. Raises BoardError and leaves `board` untouched."""
    work = board.model_copy(deep=True)
    for op in ops:
        apply_op(work, op)
    work.version = board.version + 1
    return work


def make_patch(before: Board, after: Board, ops: list[dict[str, Any]]) -> BoardPatch:
    return BoardPatch(base_version=before.version, version=after.version, ops=ops)
