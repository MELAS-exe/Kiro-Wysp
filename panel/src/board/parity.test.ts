// PAN-P1: the Panel's applyPatch gives exactly the boards the Core produced (golden fixtures made by
// scripts/make_board_fixtures.py from core/src/wysp_core/board).
import fc from "fast-check";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { Board, BoardPatch } from "../protocol";
import { applyPatch } from "./applyOps";

interface Fixture {
  name: string;
  initial: Board;
  patches: BoardPatch[];
  expected: Board[];
}

const DIR = join(
  __dirname,
  "..",
  "..",
  "..",
  "contract-tests",
  "fixtures",
  "board",
);
const fixtures: Fixture[] = readdirSync(DIR)
  .filter((f) => f.endsWith(".json"))
  .sort()
  .map((f) => JSON.parse(readFileSync(join(DIR, f), "utf-8")) as Fixture);

function replay(start: Board, patches: BoardPatch[]): Board[] {
  const boards: Board[] = [];
  let board = start;
  for (const p of patches) {
    const r = applyPatch(board, p);
    if (!r.ok) throw new Error(`patch ${p.version} refused: ${r.reason}`);
    board = r.board;
    boards.push(board);
  }
  return boards;
}

describe("board golden fixtures", () => {
  it("are present", () => {
    expect(fixtures.length).toBeGreaterThanOrEqual(5);
    for (const f of fixtures) expect(f.patches.length).toBeGreaterThan(0);
  });

  for (const f of fixtures) {
    it(`replays ${f.name} to the Core's boards, step by step`, () => {
      expect(replay(f.initial, f.patches)).toEqual(f.expected);
    });
  }

  it("prop: a patch sequence applied from any Core snapshot reaches the Core's final board (PAN-P1)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: fixtures.length - 1 }),
        fc.nat(),
        (fi, k) => {
          const f = fixtures[fi]!;
          const cut = k % (f.patches.length + 1); // 0 = from the initial board, else from a mid-stream snapshot
          const start = cut === 0 ? f.initial : f.expected[cut - 1]!;
          const boards = replay(start, f.patches.slice(cut));
          expect(boards).toEqual(f.expected.slice(cut));
        },
      ),
      { numRuns: 100 },
    );
  });
});
