import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { actionSpecs, CATALOG } from "../src/actions/index";
import { PageAgent } from "../src/cs/agent";
import type { CsActionOutcome, CsToSw } from "../src/shared/messages";
import { setPage } from "./util";

const root = join(dirname(fileURLToPath(import.meta.url)), "../src");
const PAGE = `
  <main>
    <section aria-label="Form">
      <label for="n">Name</label><input id="n" type="text" value="old">
      <label for="p">Password</label><input id="p" type="password" value="x">
      <label for="r">Region</label><select id="r"><option>All</option><option value="tr">Transylvania</option></select>
      <label><input type="checkbox"> Remember</label>
      <a href="/next">Next page</a><a href="https://evil.example/">Elsewhere</a>
      <form aria-label="Order"><button type="submit">Buy</button></form>
    </section>
  </main>`;
const R = (s: string) => `web://localhost:5180/region~form/${s}`;

function setup() {
  setPage(PAGE);
  const sent: CsToSw[] = [];
  const agent = new PageAgent(document, () => ["http://localhost:5180"], (m) => sent.push(m));
  const exec = (actionId: string, params: Record<string, unknown>, dryRun = false) =>
    agent.handle({ wysp: "execute", actionId, params, dryRun });
  return { agent, sent, exec };
}
const ok = (r: ReturnType<PageAgent["handle"]>): CsActionOutcome => {
  expect(r.ok).toBe(true);
  return (r as { result: CsActionOutcome }).result;
};
const code = (r: ReturnType<PageAgent["handle"]>) => (r.ok ? null : r.code);

describe("catalog", () => {
  it("has one file per action and the file name is the action id", () => {
    const files = readdirSync(join(root, "actions"))
      .filter((f) => f.endsWith(".ts") && !["index.ts", "types.ts", "helpers.ts", "undo.ts"].includes(f))
      .map((f) => f.replace(".ts", ""))
      .sort();
    expect([...CATALOG.keys()].sort()).toEqual(files);
  });

  it("is closed and declarative: no eval, no generic script action", () => {
    for (const dir of ["actions", "cs", "sw", "shared", "options"]) {
      for (const f of readdirSync(join(root, dir)).filter((x) => x.endsWith(".ts"))) {
        const src = readFileSync(join(root, dir, f), "utf8");
        expect(src, `${dir}/${f}`).not.toMatch(/\beval\s*\(|new\s+Function\s*\(|\.innerHTML\s*=/);
        expect(src, `${dir}/${f}`).not.toMatch(/executeScript\([^)]*\bfunc\b/);
      }
    }
    expect(actionSpecs().map((s) => s.id)).not.toContain("run_script");
  });

  it("declares risk and reversibility consistently", () => {
    for (const s of actionSpecs()) {
      expect(s.reversible).toBe(s.risk === "reversible");
      expect(s.params_schema).toMatchObject({ type: "object" });
    }
    expect(CATALOG.get("click_element")?.spec.risk).toBe("irreversible");
  });
});

describe("actions", () => {
  it("fill_field sets the value through the native setter and fires input and change; undo restores", () => {
    const { exec, agent } = setup();
    const el = document.getElementById("n") as HTMLInputElement;
    const seen: string[] = [];
    el.addEventListener("input", () => seen.push("input"));
    el.addEventListener("change", () => seen.push("change"));
    // A framework value tracker sits on the instance: the native prototype setter must bypass it.
    const tracked = vi.fn();
    Object.defineProperty(el, "value", { configurable: true, get: () => "old", set: tracked });
    const out = ok(exec("fill_field", { target: R("textbox~name"), value: "new" }));
    const protoGet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.get!;
    expect(protoGet.call(el)).toBe("new");
    expect(tracked).not.toHaveBeenCalled();
    expect(seen).toEqual(["input", "change"]);
    expect(out.undo).toMatchObject({ kind: "value", previous: "old" });
    delete (el as unknown as Record<string, unknown>).value;
    const undone = agent.handle({ wysp: "undo", record: out.undo! });
    expect(undone.ok).toBe(true);
    expect(el.value).toBe("old");
  });

  it("dry runs change nothing and return a preview", () => {
    const { exec } = setup();
    const out = ok(exec("fill_field", { target: R("textbox~name"), value: "new" }, true));
    expect(out.preview).toEqual({ before: "old", after: "new" });
    expect((document.getElementById("n") as HTMLInputElement).value).toBe("old");
  });

  it("refuses sensitive fields and invalid calls without touching the page", () => {
    const { exec } = setup();
    expect(code(exec("fill_field", { target: R("textbox~password"), value: "hack" }))).toBe(-32013);
    expect((document.getElementById("p") as HTMLInputElement).value).toBe("x");
    expect(code(exec("fill_field", { target: R("textbox~name") }))).toBe(-32602);
    expect(code(exec("fill_field", { target: "not-a-ref", value: "a" }))).toBe(-32602);
    expect(code(exec("fill_field", { target: R("textbox~nope"), value: "a" }))).toBe(-32012);
    expect(code(exec("nope", {}))).toBe(-32011);
    expect(code(exec("select_option", { target: R("combobox~region"), option: "Atlantis" }))).toBe(-32013);
    expect(code(exec("set_checked", { target: R("checkbox~remember"), checked: "yes" }))).toBe(-32602);
  });

  it("select_option and set_checked are reversible", () => {
    const { exec, agent } = setup();
    const sel = document.getElementById("r") as HTMLSelectElement;
    const o1 = ok(exec("select_option", { target: R("combobox~region"), option: "Transylvania" }));
    expect(sel.value).toBe("tr");
    agent.handle({ wysp: "undo", record: o1.undo! });
    expect(sel.value).toBe("All");
    const box = document.querySelector("input[type=checkbox]") as HTMLInputElement;
    const o2 = ok(exec("set_checked", { target: R("checkbox~remember"), checked: true }));
    expect(box.checked).toBe(true);
    agent.handle({ wysp: "undo", record: o2.undo! });
    expect(box.checked).toBe(false);
  });

  it("click_element previews the target and refuses links that leave the allowlist", () => {
    const { exec } = setup();
    const click = vi.fn();
    document.querySelector("button")!.addEventListener("click", (e) => (e.preventDefault(), click()));
    const out = ok(exec("click_element", { target: R("button~buy") }, true));
    expect(out.preview).toMatchObject({ control: { role: "button", name: "Buy" }, would_submit_form: true });
    expect(click).not.toHaveBeenCalled();
    expect(code(exec("click_element", { target: R("link~elsewhere") }, true))).toBe(-32013);
    expect(code(exec("follow_link", { target: R("link~elsewhere") }))).toBe(-32013);
    ok(exec("click_element", { target: R("button~buy") }));
    expect(click).toHaveBeenCalledOnce();
  });

  it("focus_element and scroll_into_view are ui_state actions", () => {
    const { exec } = setup();
    ok(exec("focus_element", { target: R("textbox~name") }));
    expect(document.activeElement?.id).toBe("n");
    ok(exec("scroll_into_view", { target: R("link~next-page") }));
  });
});