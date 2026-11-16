import { isSensitiveField } from "../cs/redact";
import type { ActionModule } from "./types";
import { invalid, precondition, refParam, setNativeValue, stringParam } from "./helpers";

export const spec: ActionModule["spec"] = {
  id: "select_option",
  title: { en: "Choose an option", fr: "Choisir une option" },
  description:
    "Chooses an option (by its visible label or its value) in a native drop-down list (select). Undoable. " +
    "Custom drop-downs built from divs are not supported.",
  params_schema: {
    type: "object",
    properties: { target: { type: "string", pattern: "^web://.+$" }, option: { type: "string", maxLength: 200 } },
    required: ["target", "option"],
    additionalProperties: false,
  },
  risk: "reversible",
  reversible: true,
  postconditions: [
    {
      any: [
        { ref: "${params.target}", path: "props.value", op: "eq", value: "${params.option}" },
        { ref: "${params.target}", path: "props.value_label", op: "eq", value: "${params.option}" },
      ],
    },
  ],
  guide: { ui_path: [{ text: { en: "Open ${label:params.target} and choose ${params.option}" }, target: "${params.target}" }] },
};

export const run: ActionModule["run"] = (ctx, params, dryRun) => {
  const target = refParam(params);
  const option = stringParam(params, "option", 200);
  const { el, role, name } = ctx.resolve(target);
  const win = el.ownerDocument.defaultView as (Window & typeof globalThis) | null;
  if (!(el instanceof (win?.HTMLSelectElement ?? HTMLSelectElement))) throw invalid(`${role} '${name}' is not a native select`);
  if (isSensitiveField(el) || el.disabled) throw precondition(`'${name}' cannot be changed`);
  const found = Array.from(el.options).find((o) => o.value === option || (o.label || o.text).trim() === option);
  if (!found) {
    throw precondition(`'${name}' has no option '${option}'`, {
      options: Array.from(el.options).slice(0, 20).map((o) => (o.label || o.text).trim()),
    });
  }
  const previous = el.value;
  if (dryRun) return { status: "ok", changed: [], preview: { before: previous, after: found.value } };
  setNativeValue(el, found.value);
  return { status: "ok", changed: [target], message: `Chose ${option}.`, undo: { kind: "value", ref: target, previous } };
};