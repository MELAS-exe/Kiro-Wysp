import type { ActionModule } from "./types";
import { precondition, refParam, targetSchema } from "./helpers";

const FOCUSABLE = "a[href],button,input,select,textarea,summary,[tabindex],[contenteditable='true']";

export const spec: ActionModule["spec"] = {
  id: "focus_element",
  title: { en: "Focus an element", fr: "Mettre le focus sur un élément" },
  description: "Moves keyboard focus to the control with the given ref. Changes no value.",
  params_schema: { ...targetSchema },
  risk: "ui_state",
  reversible: false,
  postconditions: [{ path: "focus", op: "contains", value: "${params.target}" }],
  guide: { ui_path: [{ text: { en: "Go to ${label:params.target}" }, target: "${params.target}" }] },
};

export const run: ActionModule["run"] = (ctx, params, dryRun) => {
  const target = refParam(params);
  const node = ctx.resolve(target);
  if (!node.el.matches(FOCUSABLE)) throw precondition(`${node.role} '${node.name}' cannot take focus`);
  if (!dryRun) (node.el as HTMLElement).focus();
  return { status: "ok", changed: [target], message: `Focused ${node.name || node.role}.` };
};