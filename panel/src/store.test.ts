import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import { emptyBoard } from "./board/applyOps";
import type { PanelMessage } from "./protocol";
import { useStore } from "./store";

describe("board patches in the store", () => {
  it("prop: a patch is applied only on its base version, otherwise a snapshot is requested or it is ignored (PAN-P2)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 15 }),
        fc.integer({ min: 0, max: 15 }),
        fc.integer({ min: 1, max: 3 }),
        (version, base, jump) => {
          const sent: PanelMessage[] = [];
          const send = vi.fn((m: PanelMessage) => (sent.push(m), true));
          const board = { ...emptyBoard(), version };
          useStore.setState({ board, send });
          useStore.getState().handle({
            type: "board.patch",
            patch: {
              base_version: base,
              version: base + jump,
              ops: [{ op: "set_stale", stale: true }],
            },
          });
          const after = useStore.getState().board;
          if (base === version) {
            expect(after.version).toBe(base + jump);
            expect(after.stale).toBe(true);
            expect(sent).toHaveLength(0);
          } else {
            expect(after).toBe(board); // untouched
            const gap = base + jump > version; // not a stale duplicate
            expect(
              sent.filter((m) => m.type === "board.snapshot_request"),
            ).toHaveLength(gap ? 1 : 0);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe("project exploration state", () => {
  it("shows what the Core reports, without the message type", () => {
    useStore.getState().handle({
      type: "explore.state",
      phase: "offer",
      note: "",
      files: 0,
      folders: 0,
      symbols: 0,
      read: 0,
      briefs: 0,
      studied_at: null,
    });
    const e = useStore.getState().explore;
    expect(e?.phase).toBe("offer");
    expect(e).not.toHaveProperty("type");
  });

  it("follows the phases the Core goes through", () => {
    const base = {
      note: "",
      files: 12,
      folders: 3,
      symbols: 40,
      read: 0,
      briefs: 0,
      studied_at: null,
    };
    for (const phase of ["mapping", "studying", "ready"] as const) {
      useStore.getState().handle({ type: "explore.state", phase, ...base });
      expect(useStore.getState().explore?.phase).toBe(phase);
    }
    expect(useStore.getState().explore?.files).toBe(12);
  });
});
