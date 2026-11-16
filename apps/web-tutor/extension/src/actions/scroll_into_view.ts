import type { ActionModule } from "./types";
import { refParam, targetSchema } from "./helpers";

export const spec: ActionModule["spec"] = {
  id: "scroll_into_view",
  title: { en: "Scroll to an element", fr: "Faire défiler jusqu'à un élément" },
  description: "Scrolls the page so the element with the given ref is visible. Changes nothing else.",
  params_schema: { ...targetSchema },
  risk: "ui_state",
  reversible: false,
  postconditions: [],
  guide: { ui_path: [{ text: { en: "Scroll to ${label:params.target}" }, target: "${params.target}" }] },
};

export const run: ActionModule["run"] = (ctx, params, dryRun) => {
  const target = refParam(params);
  const node = ctx.resolve(target);
  if (!dryRun) (node.el as HTMLElement).scrollIntoView?.({ block: "center", inline: "nearest" });
  return { status: "ok", changed: [], message: `Scrolled to ${node.name || node.role}.`, preview: dryRun ? { target } : undefined };
};