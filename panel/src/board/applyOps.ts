// Pure board operations: the TypeScript twin of core/src/wysp_core/board/ops.py.
// Patches are applied in version order; a version gap asks the Core for a fresh snapshot.
import type { Board, BoardNode, BoardOp, BoardPatch } from "../protocol";

export const MAX_NODES = 60;

export function emptyBoard(): Board {
  return { version: 0, layout: "graph", focus: [], nodes: [], edges: [], steps: [], annotations: [], stale: false };
}

/** The Core sends complete nodes, but a short one must never blank the Panel: fill what the models default. */
function completeNode(n: BoardNode): BoardNode {
  return {
    ...n,
    ref: n.ref ?? null,
    confidence: n.confidence ?? 1,
    props_view: n.props_view ?? [],
    group: n.group ?? null,
    badges: n.badges ?? [],
    order: n.order ?? null,
  };
}

function applyOp(b: Board, op: BoardOp): void {
  switch (op.op) {
    case "add_node": {
      const node = completeNode(op.node);
      const i = b.nodes.findIndex((n) => n.id === node.id);
      if (i >= 0) b.nodes[i] = node;
      else b.nodes.push(node);
      break;
    }
    case "remove_node":
      b.nodes = b.nodes.filter((n) => n.id !== op.id);
      b.edges = b.edges.filter((e) => e.source !== op.id && e.target !== op.id);
      b.annotations = b.annotations.filter((a) => a.target !== op.id);
      b.focus = b.focus.filter((f) => f !== op.id);
      for (const s of b.steps) if (s.target === op.id) s.target = null;
      break;
    case "add_edge": {
      const i = b.edges.findIndex((e) => e.id === op.edge.id);
      if (i >= 0) b.edges[i] = op.edge;
      else b.edges.push(op.edge);
      break;
    }
    case "remove_edge":
      b.edges = b.edges.filter((e) => e.id !== op.id);
      break;
    case "set_layout":
      b.layout = op.layout;
      break;
    case "set_focus": {
      const ids = new Set(b.nodes.map((n) => n.id));
      b.focus = op.ids.filter((i) => ids.has(i));
      break;
    }
    case "set_steps":
      b.steps = op.steps;
      break;
    case "update_step":
      for (const s of b.steps) {
        if (s.id === op.id) {
          if (op.status) s.status = op.status;
          if (op.text) s.text = op.text;
        }
      }
      break;
    case "add_annotation":
      b.annotations = [...b.annotations.filter((a) => a.id !== op.annotation.id), op.annotation];
      break;
    case "remove_annotation":
      b.annotations = b.annotations.filter((a) => a.id !== op.id);
      break;
    case "set_stale":
      b.stale = op.stale;
      break;
    case "clear":
      b.nodes = [];
      b.edges = [];
      b.steps = [];
      b.annotations = [];
      b.focus = [];
      break;
  }
}

export type PatchResult = { ok: true; board: Board } | { ok: false; reason: "gap" | "duplicate" };

/** Apply a patch to a board. Never mutates its input. */
export function applyPatch(board: Board, patch: BoardPatch): PatchResult {
  if (patch.version <= board.version) return { ok: false, reason: "duplicate" };
  if (patch.base_version !== board.version) return { ok: false, reason: "gap" };
  const next: Board = structuredClone(board);
  for (const op of patch.ops) applyOp(next, op);
  next.version = patch.version;
  return { ok: true, board: next };
}
