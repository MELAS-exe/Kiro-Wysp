import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { actionSpecs } from "../src/actions/index";
import { PageAgent } from "../src/cs/agent";
import { buildObservation } from "../src/cs/snapshot";
import { KEY, dashboardBody, setPage } from "./util";

interface Call {
  action_id: string;
  params: Record<string, unknown>;
  expect_error?: number;
}
const fixture = parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../contract.fixture.yaml"), "utf8")) as {
  expect: { actions: string[]; entity_kinds: string[]; min_entities: number };
  safe_calls: Call[];
  dry_run_calls: Call[];
  invalid_calls: Call[];
};

// The online kit harness does not exist yet: this replays the fixture against the extension's own logic.
describe("contract fixture replay on the demo dashboard", () => {
  const agent = () => {
    setPage(dashboardBody());
    return new PageAgent(document, () => ["http://localhost:5180"], () => undefined);
  };
  const call = (a: PageAgent, c: Call, dryRun: boolean) => a.handle({ wysp: "execute", actionId: c.action_id, params: c.params, dryRun });

  it("declares exactly the catalog and the expected kinds", () => {
    expect(actionSpecs().map((s) => s.id).sort()).toEqual([...fixture.expect.actions].sort());
    setPage(dashboardBody());
    const obs = buildObservation({ doc: document, originKey: KEY, stateVersion: 0 });
    for (const k of fixture.expect.entity_kinds) expect(new Set(obs.entities.map((e) => e.kind))).toContain(k);
    // The table and the lists are filled by the page script, which this static copy does not run.
    expect(obs.entities.length).toBeGreaterThanOrEqual(30);
  });
  it.each(fixture.safe_calls)("safe call $action_id succeeds", (c) => {
    const a = agent();
    expect(call(a, c, false)).toMatchObject({ ok: true });
  });

  it.each(fixture.dry_run_calls)("dry run $action_id succeeds and changes nothing", (c) => {
    const a = agent();
    const before = document.body.innerHTML;
    expect(call(a, c, true)).toMatchObject({ ok: true });
    expect(document.body.innerHTML).toBe(before);
  });

  it.each(fixture.invalid_calls)("invalid call $action_id fails with the expected code", (c) => {
    const a = agent();
    const before = document.body.innerHTML;
    expect(call(a, c, false)).toMatchObject({ ok: false, code: c.expect_error });
    expect(document.body.innerHTML).toBe(before);
  });
});