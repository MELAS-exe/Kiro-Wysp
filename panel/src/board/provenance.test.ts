import fc from "fast-check";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { Provenance } from "../protocol";
import { PROVENANCE_STYLE, provenanceStyle } from "./provenance";

const ALL: Provenance[] = ["observed", "inferred", "illustrative"];
const css = readFileSync(join(__dirname, "..", "styles.css"), "utf-8");

/** The declarations of the single rule `selector { ... }` (it must exist exactly once). */
function rule(selector: string): string {
  const esc = selector.replace(/\./g, "\\.");
  const found = [
    ...css.matchAll(new RegExp(`(?:^|\\n)${esc}\\s*\\{([^}]*)\\}`, "g")),
  ];
  expect(found, `rule ${selector}`).toHaveLength(1);
  return found[0]![1]!;
}
const border = (decls: string): string =>
  /(?:^|[;\s])border:\s*([^;]+)/.exec(decls)?.[1]?.trim() ?? "";

describe("provenance style", () => {
  it("prop: every provenance maps to exactly one style, and the three differ in border and label (PAN-P6)", () => {
    fc.assert(
      fc.property(fc.constantFrom(...ALL), fc.constantFrom(...ALL), (a, b) => {
        const sa = provenanceStyle(a);
        const sb = provenanceStyle(b);
        expect(provenanceStyle(a)).toBe(sa); // a function of the provenance only
        expect(sa.className).toBe(a);
        if (a !== b) {
          expect(sa.tag).not.toBe(sb.tag);
          expect(border(rule(`.wnode.${a}`))).not.toBe(
            border(rule(`.wnode.${b}`)),
          );
        }
      }),
      { numRuns: 100 },
    );
    expect(Object.keys(PROVENANCE_STYLE).sort()).toEqual([...ALL].sort());
  });

  it("matches panel-ui.md: solid 2px / dashed + 85% / hatched grey, and the legend uses the same borders", () => {
    expect(border(rule(".wnode.observed"))).toMatch(/^2px solid/);
    expect(border(rule(".wnode.inferred"))).toMatch(/dashed/);
    expect(rule(".wnode.inferred")).toMatch(/opacity:\s*0\.85/);
    expect(rule(".wnode.illustrative")).toMatch(/repeating-linear-gradient/);
    for (const p of ALL)
      expect(border(rule(`.swatch.${p}`))).toBe(border(rule(`.wnode.${p}`)));
    expect(provenanceStyle("observed").eye).toBe(true);
    expect(provenanceStyle("observed").tag).toBeNull();
  });
});
