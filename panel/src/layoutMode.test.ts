import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { initialMode, parseMode } from "./layoutMode";

describe("layout modes (requirement 1.4)", () => {
  it("the URL wins, then the remembered mode, then side", () => {
    expect(initialMode("?mode=compact", "full")).toBe("compact");
    expect(initialMode("", "full")).toBe("full");
    expect(initialMode("", null)).toBe("side");
    expect(initialMode("?mode=bogus", "bogus")).toBe("side");
    expect(parseMode("compact")).toBe("compact");
  });
});

describe("contrast (requirement 6.2)", () => {
  it("every text pair of the brand palette is at least 4.5:1 (panel/scripts/contrast.mjs)", () => {
    // Exits 1 when a text pair is below 4.5:1.
    expect(() =>
      execFileSync(process.execPath, ["scripts/contrast.mjs"], {
        stdio: "pipe",
      }),
    ).not.toThrow();
  });
});
