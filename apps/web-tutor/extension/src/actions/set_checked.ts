import type { ActionModule } from "./types";
import { boolParam, precondition, readChecked, refParam } from "./helpers";

export const spec: ActionModule["spec"] = {
  id: "set_checked",
  title: { en: "Tick or untick a box", fr: "Cocher ou décocher une case" },
  description: "Sets a checkbox, radio button or switch to checked (true) or unchecked (false). Undoable.",
  params_schema: {
    type: "object",
    properties: { target: { type: "string", pattern: "^web://.+$" }, checked: { type: "boolean" } },
    required: ["target", "checked"],
    additionalProperties: false,
  },
  risk: "reversible",
  reversible: true,
  postconditions: [{ ref: "${params.target}", path: "props.states.checked", op: "eq", value: "${params.checked}" }],
  guide: { ui_path: [{ text: { en: "Tick ${label:params.target}" }, target: "${params.target}" }] },
};

export const run: ActionModule["run"] = (ctx, params, dryRun) => {
  const target = refParam(params);
  const checked = boolParam(params, "checked");
  const { el, role, name } = ctx.resolve(target);
  const current = readChecked(el);
  if (current === null) throw precondition(`${role} '${name}' has no checked state`);
  if ((el as HTMLInputElement).disabled || el.getAttribute("aria-disabled") === "true") throw precondition(`'${name}' is disabled`);
  if ((el as HTMLInputElement).type === "radio" && !checked) throw precondition("a radio button cannot be unchecked directly");
  if (dryRun) return { status: "ok", changed: [], preview: { before: current, after: checked } };
  if (current !== checked) (el as HTMLElement).click(); // a real click keeps native and framework state in sync
  return { status: "ok", changed: [target], message: `${checked ? "Checked" : "Unchecked"} ${name || role}.`, undo: { kind: "checked", ref: target, previous: current } };
};