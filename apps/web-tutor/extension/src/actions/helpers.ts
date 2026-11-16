import { ErrorCode, WyspError } from "@wysp/adapter-sdk";

export const REF_PATTERN = "^web://.+$";

export function invalid(message: string): WyspError {
  return new WyspError(ErrorCode.INVALID_PARAMS, message);
}

export function precondition(message: string, data?: unknown): WyspError {
  return new WyspError(ErrorCode.PRECONDITION_FAILED, message, data);
}

export function refParam(params: Record<string, unknown>, name = "target"): string {
  const v = params[name];
  if (typeof v !== "string" || !/^web:\/\/.+/.test(v) || v.length > 512) throw invalid(`'${name}' must be a web:// ref`);
  return v;
}

export function stringParam(params: Record<string, unknown>, name: string, max = 500): string {
  const v = params[name];
  if (typeof v !== "string") throw invalid(`'${name}' must be a string`);
  if (v.length > max) throw invalid(`'${name}' is longer than ${max} characters`);
  return v;
}

export function boolParam(params: Record<string, unknown>, name: string): boolean {
  const v = params[name];
  if (typeof v !== "boolean") throw invalid(`'${name}' must be a boolean`);
  return v;
}

export const targetSchema = {
  type: "object",
  properties: { target: { type: "string", pattern: "^web://.+$", description: "Ref of the element (web://...)" } },
  required: ["target"],
  additionalProperties: false,
} as const;

/**
 * Sets a form control value through the native setter of its prototype, then dispatches `input` and
 * `change`, so that framework-controlled inputs (React) see the change.
 */
export function setNativeValue(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string): void {
  const win = el.ownerDocument.defaultView as (Window & typeof globalThis) | null;
  const proto =
    el instanceof (win?.HTMLTextAreaElement ?? HTMLTextAreaElement)
      ? (win?.HTMLTextAreaElement ?? HTMLTextAreaElement).prototype
      : el instanceof (win?.HTMLSelectElement ?? HTMLSelectElement)
        ? (win?.HTMLSelectElement ?? HTMLSelectElement).prototype
        : (win?.HTMLInputElement ?? HTMLInputElement).prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
}

/** Current checked state of a native checkbox/radio or an ARIA checkbox/switch. */
export function readChecked(el: Element): boolean | null {
  if (el instanceof (el.ownerDocument.defaultView?.HTMLInputElement ?? HTMLInputElement) && /^(checkbox|radio)$/i.test(el.type)) {
    return el.checked;
  }
  const aria = el.getAttribute("aria-checked");
  return aria === null ? null : aria === "true";
}