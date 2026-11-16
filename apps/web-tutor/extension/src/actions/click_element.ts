import { isSensitiveField } from "../cs/redact";
import { originAllowed } from "../shared/config";
import type { ActionModule } from "./types";
import { precondition, refParam, targetSchema } from "./helpers";

export const spec: ActionModule["spec"] = {
  id: "click_element",
  title: { en: "Click a control", fr: "Cliquer sur un contrôle" },
  description:
    "Clicks a button or other control of the page. It can submit forms or change data in the site, so it is irreversible " +
    "and needs the user's explicit click. Use the dry run to preview the target. Never leaves the allowlisted sites.",
  params_schema: { ...targetSchema },
  risk: "irreversible",
  reversible: false,
  postconditions: [],
  guide: { ui_path: [{ text: { en: "Click ${label:params.target}" }, target: "${params.target}" }] },
};

export const run: ActionModule["run"] = (ctx, params, dryRun) => {
  const target = refParam(params);
  const node = ctx.resolve(target);
  const { el, role, name, kind } = node;
  if (kind !== "control") throw precondition(`${role} '${name}' is not a control`);
  if (isSensitiveField(el)) throw precondition("sensitive fields are never clicked by Wysp");
  if ((el as HTMLButtonElement).disabled || el.getAttribute("aria-disabled") === "true") throw precondition(`'${name}' is disabled`);
  const href = el.getAttribute("href");
  let leaves = false;
  if (href) {
    const url = new URL(href, ctx.doc.location.href);
    leaves = !originAllowed(url.origin, ctx.allowlist);
    if (leaves) throw precondition("the link leaves the allowlisted sites", { host: url.host });
  }
  const form = (el as HTMLButtonElement).form;
  const submits = !!form && (el.tagName === "BUTTON" ? ((el as HTMLButtonElement).type || "submit") === "submit" : (el as HTMLInputElement).type === "submit");
  const preview = {
    control: { role, name, ref: target },
    would_submit_form: submits,
    form: submits && form ? (form.getAttribute("aria-label") ?? form.id ?? "") : undefined,
    link_path: href ? new URL(href, ctx.doc.location.href).pathname : undefined,
  };
  if (dryRun) return { status: "ok", changed: [], preview };
  (el as HTMLElement).click();
  return { status: "ok", changed: [target], message: `Clicked ${name || role}.`, preview };
};