import { describe, expect, it } from "vitest";
import { useStore } from "./store";

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
    const base = { note: "", files: 12, folders: 3, symbols: 40, read: 0, briefs: 0, studied_at: null };
    for (const phase of ["mapping", "studying", "ready"] as const) {
      useStore.getState().handle({ type: "explore.state", phase, ...base });
      expect(useStore.getState().explore?.phase).toBe(phase);
    }
    expect(useStore.getState().explore?.files).toBe(12);
  });
});
