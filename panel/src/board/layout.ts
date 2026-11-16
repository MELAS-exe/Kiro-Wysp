// Deterministic layouts. Inputs are sorted by id before layout, so the same board always gives the same positions.
import ELK from "elkjs/lib/elk.bundled.js";
import type { Board, BoardNode } from "../protocol";

export const NODE_W = 210;
const ROW_H = 15;

export function nodeHeight(n: BoardNode): number {
  // Header and padding, the label (wrapped at about 24 characters per line), then the property rows.
  const labelLines = Math.max(1, Math.ceil(n.label.length / 24));
  return 60 + labelLines * 20 + Math.min(n.props_view.length, 6) * ROW_H;
}

export type Positions = Record<string, { x: number; y: number }>;

const elk = new ELK();

function stackLayout(board: Board): Positions {
  const pos: Positions = {};
  const ordered = board.nodes.filter((n) => n.order !== null).sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id.localeCompare(b.id));
  const others = board.nodes.filter((n) => n.order === null).sort((a, b) => a.id.localeCompare(b.id));
  let y = 0;
  // Unordered nodes (the owner of the stack, other objects) sit on top, in a row.
  others.forEach((n, i) => {
    pos[n.id] = { x: i * (NODE_W + 40), y: 0 };
  });
  if (others.length) y = Math.max(...others.map(nodeHeight)) + 70;
  for (const n of ordered) {
    pos[n.id] = { x: 0, y };
    y += nodeHeight(n) + 44;
  }
  return pos;
}

function sequenceLayout(board: Board, portrait: boolean): Positions {
  const pos: Positions = {};
  let y = 0;
  [...board.nodes]
    .sort((a, b) => (a.order ?? 1e6) - (b.order ?? 1e6) || a.id.localeCompare(b.id))
    .forEach((n, i) => {
      // A narrow, tall panel reads top to bottom; a wide one left to right.
      if (portrait) {
        pos[n.id] = { x: 0, y };
        y += nodeHeight(n) + 44;
      } else pos[n.id] = { x: i * (NODE_W + 60), y: 0 };
    });
  return pos;
}

async function elkLayout(board: Board, direction: "DOWN" | "RIGHT"): Promise<Positions> {
  const nodes = [...board.nodes].sort((a, b) => a.id.localeCompare(b.id));
  const ids = new Set(nodes.map((n) => n.id));
  const graph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": direction,
      "elk.spacing.nodeNode": "36",
      "elk.layered.spacing.nodeNodeBetweenLayers": "56",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
    children: nodes.map((n) => ({ id: n.id, width: NODE_W, height: nodeHeight(n) })),
    edges: board.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .sort((a, b) => a.id.localeCompare(b.id))
      .map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  };
  const out = await elk.layout(graph);
  const pos: Positions = {};
  for (const c of out.children ?? []) pos[c.id] = { x: c.x ?? 0, y: c.y ?? 0 };
  return pos;
}

export async function computeLayout(board: Board, portrait = false): Promise<Positions> {
  if (board.nodes.length === 0) return {};
  switch (board.layout) {
    case "stack":
      return stackLayout(board);
    case "sequence":
      return sequenceLayout(board, portrait);
    case "tree":
      return elkLayout(board, "DOWN");
    default:
      return elkLayout(board, portrait ? "DOWN" : "RIGHT");
  }
}
