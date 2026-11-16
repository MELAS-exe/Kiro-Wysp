import { originAllowed } from "../shared/config";
import type { ActionModule } from "./types";
import { precondition, refParam, targetSchema } from "./helpers";

export const spec: ActionModule["spec"] = {
  id: "follow_link",
  title: { en: "Follow a link", fr: "Suivre un lien" },
  description: "Opens a link of the page. Only links to the same allowlisted site are followed.",
  params_schema: { ...targetSchema },
  risk: "ui_state",
  reversible: false,
  postconditions: [],
  guide: { ui_path: [{ text: { en: "Click the link ${label:params.target}" }, target: "${params.target}" }] },
};

export const run: ActionModule["run"] = (ctx, params, dryRun) => {
  const target = refParam(params);
  const { el, role, name } = ctx.resolve(target);
  const href = el.getAttribute("href");
  if (role !== "link" || !href) throw precondition(`${role} '${name}' is not a link`);
  const url = new URL(href, ctx.doc.location.href);
  if (url.origin !== ctx.doc.location.origin || !originAllowed(url.origin, ctx.allowlist)) {
    throw precondition("the link leaves the allowlisted site", { host: url.host });
  }
  if (!dryRun) (el as HTMLElement).click();
  return { status: "ok", changed: [target], message: `Followed ${name}.`, preview: dryRun ? { path: url.pathname + url.search } : undefined };
};