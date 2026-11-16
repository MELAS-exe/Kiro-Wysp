import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { BoardNode, BoardOp } from "../protocol";
import { applyPatch, emptyBoard } from "./applyOps";

const node = (
  id: string,
  prov: BoardNode["provenance"] = "observed",
): BoardNode => ({
  id,
  ref: prov === "observed" ? id : null,
  kind: "k",
  label: id,
  provenance: prov,
  confidence: 1,
  props_view: [],
  group: null,
  badges: [],
  order: null,
});

describe("applyPatch", () => {
  it("applies ops in order and bumps the version", () => {
    const ops: BoardOp[] = [
      { op: "add_node", node: node("a") },
      { op: "add_node", node: node("b") },
      { op: "set_layout", layout: "stack" },
    ];
    const r = applyPatch(emptyBoard(), { base_version: 0, version: 1, ops });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.board.version).toBe(1);
      expect(r.board.nodes.map((n) => n.id)).toEqual(["a", "b"]);
      expect(r.board.layout).toBe("stack");
    }
  });

  it("prop: refuses gaps and duplicates, never applies a patch with a wrong base version (PAN-P2)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 20 }),
        fc.integer({ min: 0, max: 20 }),
        (boardVersion, base) => {
          const board = { ...emptyBoard(), version: boardVersion };
          const r = applyPatch(board, {
            base_version: base,
            version: base + 1,
            ops: [{ op: "clear" }],
          });
          if (base === boardVersion) expect(r.ok).toBe(true);
          else expect(r.ok).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("does not mutate its input", () => {
    const board = emptyBoard();
    const before = JSON.stringify(board);
    applyPatch(board, {
      base_version: 0,
      version: 1,
      ops: [{ op: "add_node", node: node("a") }],
    });
    expect(JSON.stringify(board)).toBe(before);
  });

  it("removing a node removes its edges and annotations", () => {
    let b = emptyBoard();
    const ops: BoardOp[] = [
      { op: "add_node", node: node("a") },
      { op: "add_node", node: node("b") },
      {
        op: "add_edge",
        edge: {
          id: "e",
          source: "a",
          target: "b",
          kind: "contains",
          label: null,
          provenance: "observed",
        },
      },
      {
        op: "add_annotation",
        annotation: { id: "n", target: "b", text: "x", provenance: "inferred" },
      },
    ];
    const r1 = applyPatch(b, { base_version: 0, version: 1, ops });
    if (!r1.ok) throw new Error("patch failed");
    b = r1.board;
    const r2 = applyPatch(b, {
      base_version: 1,
      version: 2,
      ops: [{ op: "remove_node", id: "b" }],
    });
    if (!r2.ok) throw new Error("patch failed");
    expect(r2.board.edges).toHaveLength(0);
    expect(r2.board.annotations).toHaveLength(0);
  });
});

describe("short nodes (regression: a concept without props_view blanked the Panel)", () => {
  it("fills the fields the Core models default", () => {
    const short = {
      id: "c:s1",
      ref: null,
      kind: "step",
      label: "Describe",
      provenance: "illustrative",
      confidence: 1,
      order: 0,
    };
    const ops = [{ op: "add_node", node: short }] as unknown as BoardOp[];
    const r = applyPatch(emptyBoard(), { base_version: 0, version: 1, ops });
    expect(r.ok).toBe(true);
    if (r.ok) {
      const n = r.board.nodes[0];
      expect(n?.props_view).toEqual([]);
      expect(n?.badges).toEqual([]);
      expect(n?.group).toBeNull();
    }
  });
});
