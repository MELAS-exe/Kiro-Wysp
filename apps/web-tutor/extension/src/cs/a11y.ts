/** Roles and accessible names (dom-accessibility-api) plus the role to entity kind mapping. */
import {
  computeAccessibleDescription,
  computeAccessibleName,
  getRole,
} from "dom-accessibility-api";
import { truncate } from "./redact";

export const OVERLAY_ATTR = "data-wysp-overlay";

export type Kind =
  | "page"
  | "region"
  | "heading"
  | "form"
  | "control"
  | "dialog"
  | "table"
  | "list"
  | "chart"
  | "status";

const CONTROL_ROLES = new Set([
  "button",
  "link",
  "textbox",
  "searchbox",
  "combobox",
  "listbox",
  "checkbox",
  "radio",
  "switch",
  "slider",
  "spinbutton",
  "tab",
  "menuitem",
]);
const LANDMARK_ROLES = new Set([
  "banner",
  "navigation",
  "main",
  "complementary",
  "contentinfo",
  "search",
]);

export function roleOf(el: Element): string | null {
  const explicit = el.getAttribute("role")?.trim().split(/\s+/)[0];
  if (explicit) return explicit.toLowerCase();
  // ARIA gives password inputs no role; the tutor should still see that the field exists (its value stays redacted).
  if (el.tagName === "INPUT" && (el.getAttribute("type") ?? "").toLowerCase() === "password") return "textbox";
  return getRole(el);
}

export function nameOf(el: Element): string {
  try {
    return truncate(computeAccessibleName(el));
  } catch {
    return "";
  }
}

export function descriptionOf(el: Element): string {
  try {
    return truncate(computeAccessibleDescription(el));
  } catch {
    return "";
  }
}

export function isChartContainer(el: Element): boolean {
  return (
    el.matches("[data-chart], .chart") || !!el.closest("[data-chart], .chart")
  );
}

/** Maps an element to an entity kind, or null when it is not worth an entity. */
export function kindOf(
  el: Element,
  role: string | null,
  name: string,
): Kind | null {
  if (!role) return null;
  if (role === "heading") return "heading";
  if (CONTROL_ROLES.has(role)) return "control";
  if (role === "dialog" || role === "alertdialog") return "dialog";
  if (role === "table" || role === "grid") return "table";
  if (role === "list") return name ? "list" : null;
  if (role === "form") return name ? "form" : null;
  if (LANDMARK_ROLES.has(role)) return "region";
  if (role === "region") return name ? "region" : null;
  if ((role === "img" || role === "figure") && name && isChartContainer(el))
    return "chart";
  if (role === "status" || role === "alert" || role === "log") return "status";
  return null;
}

/** Elements whose entity can serve as the named scope ("within") of others. */
export function isScopeKind(kind: Kind | null): boolean {
  return kind === "region" || kind === "form" || kind === "dialog";
}

/** Hidden from the accessibility tree or from view (cheap checks only). */
export function isHidden(el: Element): boolean {
  if (el.hasAttribute(OVERLAY_ATTR)) return true;
  if (el.hasAttribute("hidden") || el.getAttribute("aria-hidden") === "true")
    return true;
  const style = (el.ownerDocument.defaultView ?? window).getComputedStyle(el);
  return style.display === "none" || style.visibility === "hidden";
}
