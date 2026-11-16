import { beforeEach, describe, expect, it } from "vitest";
import { buildContext, buildObservation, MAX_OPTIONS } from "../src/cs/snapshot";
import { Overlay } from "../src/cs/overlay";
import { KEY, dashboardBody, setPage, stable } from "./util";

const obs = () => buildObservation({ doc: document, originKey: KEY, stateVersion: 1 });
const find = (ref: string) => obs().entities.find((e) => e.ref === ref);

describe("snapshot of the demo dashboard", () => {
  beforeEach(() => setPage(dashboardBody()));

  it("produces entities with kinds, stable URI refs and parents", () => {
    const o = obs();
    const kinds = new Set(o.entities.map((e) => e.kind));
    for (const k of ["page", "region", "heading", "control", "table", "list", "chart"]) expect(kinds).toContain(k);
    for (const e of o.entities) expect(e.ref).toMatch(/^web:\/\/localhost:5180\/.+/);
    expect(new Set(o.entities.map((e) => e.ref)).size).toBe(o.entities.length);
    const region = find("web://localhost:5180/region~filters/combobox~region");
    expect(region?.kind).toBe("control");
    expect(region?.parent).toBe("web://localhost:5180/region~filters");
    expect(region?.props).toMatchObject({ role: "combobox", value: "All regions" });
  });

  it("lists the options of a combobox (at most 20) and the headers of a table", () => {
    const region = find("web://localhost:5180/region~filters/combobox~region");
    expect(region?.props?.options).toEqual(["All regions", "Transylvania", "Salem", "Sleepy Hollow", "Bayou"]);
    const table = obs().entities.find((e) => e.kind === "table");
    expect(table?.props?.columns).toEqual(["Order", "Region", "Category", "Total"]);
  });

  it("caps options at 20 and table rows at 10, and truncates long text to 200", () => {
    const opts = Array.from({ length: 40 }, (_, i) => `<option>o${i}</option>`).join("");
    const rows = Array.from({ length: 25 }, (_, i) => `<tr><td>r${i}</td></tr>`).join("");
    setPage(`<main><label for="s">Pick</label><select id="s">${opts}</select><table aria-label="T"><tr><th>A</th></tr>${rows}</table><h1>${"x".repeat(500)}</h1></main>`);
    const o = obs();
    expect((o.entities.find((e) => e.label === "Pick")?.props?.options as string[]).length).toBe(MAX_OPTIONS);
    const t = o.entities.find((e) => e.kind === "table");
    expect((t?.props?.rows as string[][]).length).toBe(10);
    expect(t?.props?.row_count).toBe(25);
    expect(o.entities.find((e) => e.kind === "heading")?.label.length).toBeLessThanOrEqual(200);
  });

  it("traverses open shadow roots", () => {
    setPage(`<main><div id="host"></div></main>`);
    const root = document.getElementById("host")!.attachShadow({ mode: "open" });
    root.innerHTML = `<button>Inside shadow</button>`;
    expect(obs().entities.some((e) => e.label === "Inside shadow")).toBe(true);
  });

  it("reports state, link paths (same origin only) and counts", () => {
    setPage(`<main><a href="/reports">Reports</a><a href="https://evil.example/x">Other</a><input type="checkbox" checked aria-label="On"></main>`);
    const o = obs();
    expect(o.entities.find((e) => e.label === "Reports")?.props?.href_path).toBe("/reports");
    expect(o.entities.find((e) => e.label === "Other")?.props?.href_path).toBeUndefined();
    expect(o.entities.find((e) => e.label === "On")?.props?.states).toMatchObject({ checked: true });
    expect(o.counts?.control).toBe(3);
  });

  it("builds a context under 8 KB", () => {
    const ctx = buildContext(document, KEY, true);
    expect(JSON.stringify(ctx).length).toBeLessThan(8192);
    expect(ctx.summary).toContain("Test page");
  });

  it("keeps URLs free of query strings and fragments", () => {
    setPage(dashboardBody(), "http://localhost:5180/p?token=SECRET#frag");
    expect(JSON.stringify(obs())).not.toContain("SECRET");
  });
});

describe("prop: WEB-P4 overlay invisibility", () => {
  it("snapshots are identical with the overlay visible and without it", () => {
    setPage(dashboardBody());
    const before = stable(obs());
    const overlay = new Overlay(document, () => undefined);
    const target = document.querySelector("button")!;
    overlay.show({ ref: "web://localhost:5180/x", durationMs: 0, getEl: () => target }, "pulse", "Click here");
    expect(document.querySelector("[data-wysp-overlay]")).not.toBeNull();
    expect(stable(obs())).toEqual(before);
    expect(document.body.innerHTML).not.toContain("wysp-overlay"); // nothing added inside the page body
    overlay.clear();
    expect(document.querySelector("[data-wysp-overlay]")).toBeNull();
    expect(stable(obs())).toEqual(before);
  });
});