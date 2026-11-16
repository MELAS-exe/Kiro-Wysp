/** The accessibility-oriented snapshot: entities from roles and names, redacted before they leave. */
import type { Context, Entity, Observation } from "@wysp/adapter-sdk";
import { originAllowed } from "../shared/config";
import { descriptionOf, roleOf } from "./a11y";
import { collectNodes, pageRef, resolveRef, type Node } from "./locators";
import {
  isSensitiveField,
  safeValue,
  scrub,
  sensitiveValues,
  truncate,
} from "./redact";

/** An Observation whose optional lists are always present. */
export type Snapshot = Observation & {
  entities: Entity[];
  focus: string[];
  links: NonNullable<Observation["links"]>;
  counts: Record<string, number>;
};

/** Origin and path only: query strings and fragments can carry tokens. */
function pageUrl(doc: Document): string {
  const l = doc.location;
  return l ? l.origin + l.pathname : "";
}

export const MAX_ENTITIES = 500;
export const MAX_OPTIONS = 20;
export const MAX_ROWS = 10;

type Props = Record<string, unknown>;

function texts(els: Iterable<Element>, max: number, cut = 80): string[] {
  const out: string[] = [];
  for (const el of els) {
    if (out.length >= max) break;
    out.push(truncate(el.textContent ?? "", cut));
  }
  return out;
}

function statesOf(el: Element): Props {
  const s: Props = {};
  const input = el as HTMLInputElement;
  const tri = (attr: string): boolean | "mixed" | undefined => {
    const v = el.getAttribute(attr);
    return v === null ? undefined : v === "mixed" ? "mixed" : v === "true";
  };
  const type = (el.getAttribute("type") ?? "").toLowerCase();
  if (el.tagName === "INPUT" && (type === "checkbox" || type === "radio"))
    s.checked = input.checked;
  else if (tri("aria-checked") !== undefined) s.checked = tri("aria-checked");
  if (tri("aria-expanded") !== undefined) s.expanded = tri("aria-expanded");
  if (tri("aria-selected") !== undefined) s.selected = tri("aria-selected");
  if (tri("aria-pressed") !== undefined) s.pressed = tri("aria-pressed");
  if (
    (el as HTMLButtonElement).disabled === true ||
    el.getAttribute("aria-disabled") === "true"
  )
    s.disabled = true;
  if (
    (el as HTMLInputElement).required === true ||
    el.getAttribute("aria-required") === "true"
  )
    s.required = true;
  if (el.getAttribute("aria-invalid") === "true") s.invalid = true;
  return s;
}

function optionsOf(el: Element): string[] | undefined {
  if (el.tagName === "SELECT") {
    return Array.from((el as HTMLSelectElement).options)
      .slice(0, MAX_OPTIONS)
      .map((o) => truncate(o.label || o.text, 80));
  }
  const role = roleOf(el);
  if (role === "combobox" || role === "listbox") {
    const controlled = el
      .getAttribute("aria-controls")
      ?.split(/\s+/)
      .map((id) => el.ownerDocument.getElementById(id));
    const scope = controlled?.find((x): x is HTMLElement => !!x) ?? el;
    const options = scope.querySelectorAll('[role="option"]');
    if (options.length) return texts(options, MAX_OPTIONS);
  }
  return undefined;
}

function tableProps(el: Element): Props {
  const headers = el.querySelectorAll('th, [role="columnheader"]');
  const rowEls = Array.from(el.querySelectorAll('tr, [role="row"]')).filter(
    (r) => r.querySelector('td, [role="cell"], [role="gridcell"]') !== null,
  );
  const rows = rowEls
    .slice(0, MAX_ROWS)
    .map((r) =>
      texts(r.querySelectorAll('td, [role="cell"], [role="gridcell"]'), 12, 60),
    );
  return { columns: texts(headers, 12, 60), rows, row_count: rowEls.length };
}

function propsOf(
  n: Node,
  doc: Document,
  originKey: string,
  desc: string,
): Props {
  const { el } = n;
  const p: Props = { role: n.role, name: n.name };
  if (desc) p.description = desc;
  switch (n.kind) {
    case "control": {
      const states = statesOf(el);
      if (Object.keys(states).length) p.states = states;
      const type = (el.getAttribute("type") ?? "").toLowerCase();
      if (!/^(checkbox|radio|button|submit|reset|image)$/.test(type) && el.tagName !== "BUTTON") {
        const v = safeValue(el);
        if (v !== undefined) p.value = v;
      }
      if (el.tagName === "SELECT" && !isSensitiveField(el)) {
        const sel = (el as HTMLSelectElement).selectedOptions[0];
        if (sel) p.value_label = truncate(sel.label || sel.text, 80);
      }
      const options = optionsOf(el);
      if (options) p.options = options;
      if (n.role === "link") {
        const href = el.getAttribute("href");
        if (href) {
          try {
            const url = new URL(
              href,
              doc.location?.href ?? "http://localhost/",
            );
            if (url.host === originKey)
              p.href_path = truncate(url.pathname, 120);
          } catch {
            /* not a URL */
          }
        }
      }
      break;
    }
    case "heading": {
      const level = Number(
        el.getAttribute("aria-level") ??
          /^H([1-6])$/.exec(el.tagName)?.[1] ??
          0,
      );
      if (level) p.level = level;
      break;
    }
    case "table":
      Object.assign(p, tableProps(el));
      break;
    case "list":
      p.items = texts(el.querySelectorAll('li, [role="listitem"]'), MAX_ROWS);
      break;
    case "chart":
      p.summary = desc || n.name;
      break;
    case "status":
      p.text = truncate(el.textContent ?? "");
      break;
    case "dialog":
      p.modal = el.getAttribute("aria-modal") === "true";
      break;
    default:
      break;
  }
  const r = el.getBoundingClientRect();
  p.bbox = [
    Math.round(r.x),
    Math.round(r.y),
    Math.round(r.width),
    Math.round(r.height),
  ]; // volatile
  return p;
}

function scrubDeep<T>(value: T, secrets: readonly string[]): T {
  if (typeof value === "string") return scrub(value, secrets) as T;
  if (Array.isArray(value)) return value.map((v) => scrubDeep(v, secrets)) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, scrubDeep(v, secrets)]),
    ) as T;
  }
  return value;
}

export interface SnapshotInput {
  doc: Document;
  originKey: string;
  stateVersion: number;
  scope?: { level?: string; root?: string | null };
  /** Computed by the caller from Date for determinism in tests. */
  now?: () => Date;
}

export function buildObservation(input: SnapshotInput): Snapshot {
  const { doc, originKey } = input;
  const secrets = sensitiveValues(doc);
  let nodes = collectNodes(doc, originKey);
  const level = input.scope?.level ?? "focus";
  if (input.scope?.root && input.scope.root !== pageRef(originKey)) {
    const root = resolveRef(doc, input.scope.root, originKey, nodes);
    nodes = nodes.filter((n) => {
      for (let c: Node | null = n; c; c = c.parent) if (c === root) return true;
      return false;
    });
  }
  if (level === "summary") nodes = nodes.filter((n) => n.kind !== "control");

  const counts: Record<string, number> = { page: 1 };
  for (const n of nodes) counts[n.kind] = (counts[n.kind] ?? 0) + 1;
  const truncated = nodes.length > MAX_ENTITIES - 1;
  const kept = truncated ? nodes.slice(0, MAX_ENTITIES - 1) : nodes;
  const keptRefs = new Set(kept.map((n) => n.ref));

  const page: Entity = {
    ref: pageRef(originKey),
    kind: "page",
    label: truncate(scrub(doc.title || originKey, secrets)),
    parent: null,
    props: { url: pageUrl(doc), title: truncate(doc.title ?? "") },
  };
  const entities: Entity[] = [page];
  for (const n of kept) {
    const parent =
      n.parent && keptRefs.has(n.parent.ref) ? n.parent.ref : page.ref;
    const desc = scrub(descriptionOf(n.el), secrets);
    entities.push({
      ref: n.ref,
      kind: n.kind,
      label: truncate(n.name || (n.kind === "status" ? (n.el.textContent ?? "") : "") || n.role),
      parent,
      props: scrubDeep(
        propsOf(n, doc, originKey, desc),
        secrets,
      ) as Entity["props"],
    });
  }

  const focus: string[] = [];
  const active = doc.activeElement;
  const byEl = new Map(kept.map((n) => [n.el, n.ref] as const));
  if (active && byEl.has(active)) focus.push(byEl.get(active) as string);
  for (const n of kept)
    if (n.kind === "dialog" && !focus.includes(n.ref)) focus.push(n.ref);

  return {
    observation_id: crypto.randomUUID(),
    state_version: input.stateVersion,
    captured_at: (input.now ?? (() => new Date()))().toISOString(),
    scope: {
      level: level as "summary" | "focus" | "full",
      root: input.scope?.root ?? null,
      depth: null,
    },
    entities,
    links: [],
    focus,
    truncated,
    counts,
  };
}

/** An observation with nothing in it, for origins that are not allowlisted (Requirement 1.4). */
export function emptyObservation(
  stateVersion: number,
  now: () => Date = () => new Date(),
): Observation {
  return {
    observation_id: crypto.randomUUID(),
    state_version: stateVersion,
    captured_at: now().toISOString(),
    scope: { level: "focus", root: null, depth: null },
    entities: [],
    links: [],
    focus: [],
    truncated: false,
    counts: { not_allowed: 1 },
  };
}

/** The only door from the DOM to the outside: allowlist check first, then the snapshot. */
export function guardedObservation(
  input: SnapshotInput & { allowlist: readonly string[] },
): Observation {
  const origin = input.doc.location?.origin;
  if (!originAllowed(origin, input.allowlist))
    return emptyObservation(input.stateVersion, input.now);
  return buildObservation(input);
}

export function buildContext(
  doc: Document,
  originKey: string,
  allowed: boolean,
  obs?: Snapshot,
): Context {
  if (!allowed) {
    return {
      summary: "The active page is not on the allowlist, so it is not read.",
      facts: { not_allowed: true },
      focus: [],
    };
  }
  const o = obs ?? buildObservation({ doc, originKey, stateVersion: 0 });
  const headings = o.entities
    .filter((e) => e.kind === "heading")
    .slice(0, 8)
    .map((e) => e.label);
  const dialogs = o.entities
    .filter((e) => e.kind === "dialog")
    .map((e) => e.label);
  const role = (e: Entity): string =>
    String((e.props as Props | undefined)?.role ?? "");
  const summary = truncate(
    `Page "${doc.title}" (${originKey}). ${o.counts?.["control"] ?? 0} controls, ${o.counts?.["region"] ?? 0} regions.` +
      (dialogs.length ? ` Open dialog: ${dialogs.join(", ")}.` : ""),
    300,
  );
  return {
    summary,
    facts: {
      url: pageUrl(doc),
      title: truncate(doc.title ?? ""),
      headings,
      open_dialogs: dialogs,
      focused: o.focus.slice(0, 3),
      controls: o.entities
        .filter((e) => e.kind === "control")
        .slice(0, 12)
        .map((e) => `${role(e)}: ${e.label}`),
    },
    focus: o.focus,
  };
}
