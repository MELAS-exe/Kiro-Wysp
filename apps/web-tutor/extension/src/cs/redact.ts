/**
 * Redaction. Runs before anything leaves the content script. Sensitive fields never reveal their value
 * (password, credit card, one-time code, hidden, or marked data-wysp-sensitive) and long texts are truncated.
 */

export const REDACTED = "[redacted]";
export const MAX_TEXT = 200;

export function truncate(text: string, max = MAX_TEXT): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

const SENSITIVE_AUTOCOMPLETE =
  /^(cc-.+|one-time-code|current-password|new-password)$/;

export function isSensitiveField(el: Element): boolean {
  if (el.closest("[data-wysp-sensitive]")) return true;
  const tag = el.tagName.toLowerCase();
  if (tag !== "input" && tag !== "textarea" && tag !== "select") return false;
  const type = (el.getAttribute("type") ?? "").toLowerCase();
  if (type === "password" || type === "hidden") return true;
  const tokens = (el.getAttribute("autocomplete") ?? "")
    .toLowerCase()
    .split(/\s+/);
  return tokens.some((t) => SENSITIVE_AUTOCOMPLETE.test(t));
}

/** The value of a form control as it may leave the page: redacted for sensitive fields, truncated otherwise. */
export function safeValue(el: Element): string | undefined {
  if (!("value" in el)) return undefined;
  if (isSensitiveField(el)) return REDACTED;
  const value = (el as HTMLInputElement).value;
  return typeof value === "string" ? truncate(value) : undefined;
}

/** Values of sensitive fields currently in the document (used to scrub derived texts such as names). */
export function sensitiveValues(root: ParentNode): string[] {
  const values = new Set<string>();
  root.querySelectorAll("input, textarea, select").forEach((el) => {
    if (isSensitiveField(el)) {
      const v = (el as HTMLInputElement).value;
      if (typeof v === "string" && v.length >= 4) values.add(v);
    }
  });
  return [...values];
}

export function scrub(text: string, secrets: readonly string[]): string {
  let out = text;
  for (const secret of secrets)
    if (out.includes(secret)) out = out.split(secret).join(REDACTED);
  return out;
}
