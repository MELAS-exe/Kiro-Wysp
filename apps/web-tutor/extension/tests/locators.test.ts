import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { ErrorCode, WyspError } from "@wysp/adapter-sdk";
import { collectNodes, parseRef, parseSegment, resolveRef, slug } from "../src/cs/locators";
import { KEY, setPage } from "./util";

const names = ["Save", "Cancel", "Name", "Send"];
const itemArb = fc.record({
  type: fc.constantFrom("button", "link", "textbox", "checkbox"),
  label: fc.constantFrom(...names),
});
type Item = { type: string; label: string };
const html = (item: Item): string =>
  item.type === "button"
    ? `<button>${item.label}</button>`
    : item.type === "link"
      ? `<a href="/x">${item.label}</a>`
      : item.type === "textbox"
        ? `<input type="text" aria-label="${item.label}">`
        : `<input type="checkbox" aria-label="${item.label}">`;
const regionArb = fc.record({ name: fc.option(fc.constantFrom("Alpha", "Beta"), { nil: null }), items: fc.array(itemArb, { maxLength: 6 }) });
const pageHtml = (regions: Array<{ name: string | null; items: Item[] }>): string =>
  `<main>${regions.map((r) => (r.name ? `<section aria-label="${r.name}">${r.items.map(html).join("")}</section>` : r.items.map(html).join(""))).join("")}</main>`;

describe("prop: WEB-P2 locator round trip", () => {
  it("every snapshot ref resolves to its own element, and refs are unique", () => {
    fc.assert(
      fc.property(fc.array(regionArb, { maxLength: 4 }), (regions) => {
        setPage(pageHtml(regions));
        const nodes = collectNodes(document, KEY);
        expect(new Set(nodes.map((n) => n.ref)).size).toBe(nodes.length);
        for (const n of nodes) expect(resolveRef(document, n.ref, KEY, nodes).el).toBe(n.el);
      }),
      { numRuns: 60 },
    );
  });

  it("an ambiguous locator fails with TARGET_NOT_FOUND and lists at most 5 candidates", () => {
    setPage(`<main>${"<button>Save</button>".repeat(7)}</main>`);
    try {
      resolveRef(document, `web://${KEY}/button~save`, KEY);
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(WyspError);
      const err = e as WyspError;
      expect(err.code).toBe(ErrorCode.TARGET_NOT_FOUND);
      expect((err.data as { candidates: unknown[] }).candidates.length).toBe(5);
    }
  });

  it("a ref without index resolves only when the role and name are unique in the page", () => {
    fc.assert(
      fc.property(fc.array(regionArb, { maxLength: 3 }), (regions) => {
        setPage(pageHtml(regions));
        const nodes = collectNodes(document, KEY);
        for (const n of nodes) {
          const seg = parseSegment(n.segment);
          if (!seg || !seg.slug) continue;
          const loose = `web://${KEY}/${seg.role}~${seg.slug}`;
          const same = nodes.filter((m) => m.role === seg.role && slug(m.name) === seg.slug);
          if (same.length === 1) expect(resolveRef(document, loose, KEY, nodes).el).toBe(n.el);
          else expect(() => resolveRef(document, loose, KEY, nodes)).toThrow(WyspError);
        }
      }),
      { numRuns: 40 },
    );
  });

  it("refuses refs of another origin and malformed refs", () => {
    setPage("<main><button>Save</button></main>");
    expect(() => resolveRef(document, "web://other.example/button~save", KEY)).toThrow(WyspError);
    expect(() => resolveRef(document, "blender://x", KEY)).toThrow(WyspError);
    expect(parseRef("web://localhost:5180/region~a/button~b#2")?.segments).toEqual(["region~a", "button~b#2"]);
  });

  it("slugs never contain the separators of the ref syntax", () => {
    fc.assert(fc.property(fc.string(), (s) => !/[~/#>]/.test(slug(s))));
  });
});

describe("prop: WEB-P3 ref stability", () => {
  it("refs of unique elements of a region do not change when other regions change", () => {
    const base = `<section aria-label="Alpha"><button>Save</button><input type="text" aria-label="Name"><a href="/x">Help</a></section>`;
    fc.assert(
      fc.property(fc.array(itemArb, { maxLength: 8 }), fc.array(itemArb, { maxLength: 8 }), (before, after) => {
        const page = (items: Item[]) => `<main>${base}<section aria-label="Beta">${items.map(html).join("")}</section></main>`;
        setPage(page(before));
        const refsA = (): string[] =>
          collectNodes(document, KEY)
            .filter((n) => n.ref.includes("region~alpha"))
            .map((n) => n.ref)
            .sort();
        const first = refsA();
        setPage(page(after));
        expect(refsA()).toEqual(first);
      }),
      { numRuns: 40 },
    );
  });
});