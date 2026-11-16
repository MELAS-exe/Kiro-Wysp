import { isSensitiveField } from "../cs/redact";
import type { ActionModule } from "./types";
import { invalid, precondition, refParam, setNativeValue, stringParam } from "./helpers";

export const spec: ActionModule["spec"] = {
  id: "fill_field",
  title: { en: "Type into a field", fr: "Saisir dans un champ" },
  description:
    "Replaces the text of a text field (textbox, search box, text area) with the given value. Undoable. " +
    "Refuses password, card, one-time-code and hidden fields.",
  params_schema: {
    type: "object",
    properties: {
      target: { type: "string", pattern: "^web://.+$" },
      value: { type: "string", maxLength: 500 },
    },
    required: ["target", "value"],
    additionalProperties: false,
  },
  risk: "reversible",
  reversible: true,
  postconditions: [{ ref: "${params.target}", path: "props.value", op: "eq", value: "${params.value}" }],
  guide: { ui_path: [{ text: { en: "Type ${params.value} in ${label:params.target}" }, target: "${params.target}" }] },
};

export const run: ActionModule["run"] = (ctx, params, dryRun) => {
  const target = refParam(params);
  const value = stringParam(params, "value");
  const { el, role, name } = ctx.resolve(target);
  const win = el.ownerDocument.defaultView as (Window & typeof globalThis) | null;
  const isText =
    el instanceof (win?.HTMLTextAreaElement ?? HTMLTextAreaElement) ||
    (el instanceof (win?.HTMLInputElement ?? HTMLInputElement) &&
      !/^(checkbox|radio|button|submit|reset|file|image|range|color)$/i.test(el.type));
  if (!isText) throw invalid(`${role} '${name}' is not a text field`);
  if (isSensitiveField(el)) throw precondition("sensitive fields are never filled by Wysp");
  const field = el as HTMLInputElement | HTMLTextAreaElement;
  if (field.disabled || field.readOnly) throw precondition(`'${name}' is disabled or read-only`);
  const previous = field.value;
  if (dryRun) return { status: "ok", changed: [], preview: { before: previous.slice(0, 200), after: value.slice(0, 200) } };
  setNativeValue(field, value);
  return {
    status: "ok",
    changed: [target],
    message: `Typed into ${name || role}.`,
    undo: { kind: "value", ref: target, previous },
  };
};