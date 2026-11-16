import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { Board, BoardEdge, BoardNode } from "../protocol";
import { emptyBoard } from "./applyOps";
import { computeLayout } from "./layout";

const nodeArb = (id: string): fc.Arbitrary<BoardNode> =>
  fc.record({
    id: fc.constant(id),
    ref: fc.constant(null),
    kind: fc.constantFrom("object", "modifier", "concept"),
    label: fc.string({ maxLength: 60 }),
    provenance: fc.constantFrom(
      "observed" as const,
      "inferred" as const,
      "illustrative" as const,
    ),
    confidence: fc.constant(1),
    props_view: fc.array(
      fc
        .tuple(fc.string({ maxLength: 8 }), fc.string({ maxLength: 8 }))
        .map(([k, v]) => [k, v]),
      { maxLength: 8 },
    ),
    group: fc.constant(null),
    badges: fc.constant([] as string[]),
    order: fc.option(fc.integer({ min: 0, max: 4 }), { nil: null }), // ties on purpose
  });

const boardArb: fc.Arbitrary<Board> = fc
  .integer({ min: 1, max: 9 })
  .chain((n) => {
    const ids = Array.from({ length: n }, (_, i) => `n${i}`);
    return fc.record({
      nodes: fc.tuple(...ids.map(nodeArb)),
      edges: fc.array(
        fc.record({
          id: fc.uuid(),
          source: fc.constantFrom(...ids),
          target: fc.constantFrom(...ids),
          kind: fc.constant("link"),
          label: fc.constant(null),
          provenance: fc.constant("observed" as const),
        }),
        { maxLength: 10 },
      ),
      layout: fc.constantFrom(
        "stack" as const,
        "tree" as const,
        "graph" as const,
        "sequence" as const,
      ),
    });
  })
  .map(({ nodes, edges, layout }) => ({
    ...emptyBoard(),
    layout,
    nodes: nodes as BoardNode[],
    edges: edges as BoardEdge[],
  }));

const shuffled = <T>(xs: T[], seed: number): T[] => {
  // deterministic Fisher-Yates driven by the seed
  const out = [...xs];
  let s = seed >>> 0 || 1;
  for (let i = out.length - 1; i > 0; i--) {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    const j = s % (i + 1);
    [out[i], out[j]] = [out[j]!, out[i]!];
  }
  return out;
};

describe("layout", () => {
  it("prop: same positions for the same board whatever the order of nodes and edges (PAN-P3)", async () => {
    await fc.assert(
      fc.asyncProperty(
        boardArb,
        fc.integer(),
        fc.boolean(),
        async (board, seed, portrait) => {
          const a = await computeLayout(board, portrait);
          const permuted = {
            ...board,
            nodes: shuffled(board.nodes, seed),
            edges: shuffled(board.edges, seed + 1),
          };
          const b = await computeLayout(permuted, portrait);
          expect(b).toEqual(a);
          expect(Object.keys(a).sort()).toEqual(
            board.nodes.map((n) => n.id).sort(),
          );
          const again = await computeLayout(board, portrait);
          expect(again).toEqual(a);
        },
      ),
      { numRuns: 50 },
    );
  });

  it("an empty board has no positions", async () => {
    expect(await computeLayout(emptyBoard())).toEqual({});
  });
});
