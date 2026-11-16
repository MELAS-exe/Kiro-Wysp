import { describe, expect, it } from "vitest";
import { ActionRegistry, defineAction } from "../src/actions";
import { ErrorCode, WyspError } from "../src/errors";

const rename = () => {
  const calls: { title: string; dryRun: boolean }[] = [];
  const action = defineAction<{ card: string; title: string }>({
    id: "rename_card",
    title: "Rename a card",
    description: "Change the title of a card.",
    risk: "reversible",
    params_schema: {
      type: "object",
      properties: { card: { type: "string", pattern: "^mock://card/c[0-9]+$" }, title: { type: "string", minLength: 1, maxLength: 80 } },
      required: ["card", "title"],
      additionalProperties: false,
    },
    postconditions: [{ ref: "${params.card}", path: "label", op: "eq", value: "${params.title}" }],
    handler: (p, dryRun) => {
      calls.push({ title: p.title, dryRun });
      return { changed: [p.card], undo_token: "u1" };
    },
  });
  return { action, calls };
};

describe("defineAction", () => {
  it("builds the catalog entry with the reversible flag derived from the risk", () => {
    const { action } = rename();
    expect(action.spec).toMatchObject({ id: "rename_card", risk: "reversible", reversible: true, preconditions: [] });
    expect(action.spec.postconditions).toHaveLength(1);
  });

  it("refuses inconsistent risk and code-running actions", () => {
    const base = { title: "t", description: "d", params_schema: { type: "object" }, handler: () => {} };
    expect(() => defineAction({ ...base, id: "a", risk: "reversible", reversible: false })).toThrow(/requires reversible=true/);
    expect(() => defineAction({ ...base, id: "b", risk: "irreversible", reversible: true })).toThrow(/requires reversible=false/);
    expect(() => defineAction({ ...base, id: "run_script", risk: "ui_state" })).toThrow(/forbidden/);
  });

  it("rejects invalid params with -32602 before the handler runs", async () => {
    const { action, calls } = rename();
    for (const bad of [{}, { card: "nope", title: "x" }, { card: "mock://card/c1", title: "" }, { card: "mock://card/c1", title: "x", extra: 1 }]) {
      const err = await action.run(bad).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(WyspError);
      expect((err as WyspError).code).toBe(ErrorCode.INVALID_PARAMS);
      expect((err as WyspError).data).toHaveProperty("problems");
    }
    expect(calls).toEqual([]);
  });

  it("passes valid params and the dry-run flag to the handler", async () => {
    const { action, calls } = rename();
    expect(await action.run({ card: "mock://card/c1", title: "New" }, true)).toEqual({ changed: ["mock://card/c1"], undo_token: "u1" });
    expect(calls).toEqual([{ title: "New", dryRun: true }]);
  });
});

describe("ActionRegistry", () => {
  it("lists specs and executes calls, adding status and state_version", async () => {
    const { action, calls } = rename();
    const registry = new ActionRegistry([action], () => 12);
    expect(registry.specs().map((s) => s.id)).toEqual(["rename_card"]);
    const result = await registry.execute({ call: { action_id: "rename_card", params: { card: "mock://card/c2", title: "Hi" } } });
    expect(result).toEqual({ status: "ok", changed: ["mock://card/c2"], undo_token: "u1", state_version: 12 });
    expect(calls).toEqual([{ title: "Hi", dryRun: false }]);
  });

  it("maps unknown actions to -32011 and malformed calls to -32602", async () => {
    const registry = new ActionRegistry([rename().action]);
    await expect(registry.execute({ call: { action_id: "nope", params: {} } })).rejects.toMatchObject({ code: ErrorCode.ACTION_NOT_FOUND });
    await expect(registry.execute({})).rejects.toMatchObject({ code: ErrorCode.INVALID_PARAMS });
  });

  it("refuses duplicate ids", () => {
    const { action } = rename();
    expect(() => new ActionRegistry([action, action])).toThrow(/duplicate/);
  });
});
