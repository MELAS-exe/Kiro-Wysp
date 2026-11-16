/**
 * Locators and refs.
 *
 *   ref     = web://<host[:port]>/<segment>            (a top-level element)
 *           | web://<host[:port]>/<scope>/<segment>    (inside the nearest named region, form or dialog)
 *           | web://<host[:port]>/page
 *   segment = <role>~<slug>[#<n>]     role + accessible name (+ 1-based index when role and name repeat in a scope)
 *           | <role>~#<n>             no accessible name
 *           | <role>~@<testid>        no accessible name, data-testid as fallback
 *
 * Refs are computed from the DOM at observation time and resolved again at execution time: nothing
 * about elements is cached, so a ref keeps working as long as role, name and position in its scope hold.
 */
import { WyspError, ErrorCode } from "@wysp/adapter-sdk";
import {
  isHidden,
  isScopeKind,
  kindOf,
  nameOf,
  roleOf,
  type Kind,
} from "./a11y";
import { scrub, sensitiveValues } from "./redact";

export interface Node {
  el: Element;
  role: string;
  name: string;
  kind: Kind;
  scope: Node | null;
  parent: Node | null;
  segment: string;
  ref: string;
}

export const MAX_SLUG = 60;

export function slug(name: string): string {
  const base = name.normalize("NFKC").toLowerCase().trim().replace(/\s+/g, "-");
  return encodeURIComponent(base)
    .replace(
      /[~!*()']/g,
      (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
    )
    .slice(0, MAX_SLUG);
}

export function pageRef(originKey: string): string {
  return `web://${originKey}/page`;
}

export interface ParsedSegment {
  role: string;
  slug: string;
  nth?: number;
  testId?: string;
}

export function parseSegment(segment: string): ParsedSegment | null {
  const at = segment.indexOf("~");
  if (at <= 0) return null;
  const role = segment.slice(0, at);
  const rest = segment.slice(at + 1);
  if (rest.startsWith("@"))
    return { role, slug: "", testId: decodeURIComponent(rest.slice(1)) };
  const hash = rest.lastIndexOf("#");
  if (hash >= 0 && /^\d+$/.test(rest.slice(hash + 1))) {
    return {
      role,
      slug: rest.slice(0, hash),
      nth: Number(rest.slice(hash + 1)),
    };
  }
  return { role, slug: rest };
}

export function parseRef(
  ref: string,
): { key: string; segments: string[] } | null {
  const m = /^web:\/\/([^/]+)\/(.+)$/.exec(ref);
  if (!m) return null;
  return { key: m[1] as string, segments: (m[2] as string).split("/") };
}

function* childrenOf(el: Element): Generator<Element> {
  if (el.shadowRoot) yield* Array.from(el.shadowRoot.children); // open shadow roots only
  yield* Array.from(el.children);
}

/** All entity-worthy elements of the document, in document order, with refs assigned. */
export function collectNodes(doc: Document, originKey: string): Node[] {
  const secrets = sensitiveValues(doc);
  const nodes: Node[] = [];

  const walk = (el: Element, parent: Node | null, scope: Node | null): void => {
    if (isHidden(el)) return;
    const role = roleOf(el);
    const name = scrub(nameOf(el), secrets);
    const kind = kindOf(el, role, name);
    let node: Node | null = null;
    if (kind && role) {
      node = {
        el,
        role,
        name,
        kind,
        scope: isScopeKind(kind) ? null : scope,
        parent,
        segment: "",
        ref: "",
      };
      nodes.push(node);
    }
    const nextScope = node && isScopeKind(node.kind) ? node : scope;
    for (const child of childrenOf(el)) walk(child, node ?? parent, nextScope);
  };
  if (doc.body) walk(doc.body, null, null);

  // Assign segments. The index is added only when role + name repeat inside the same scope. Scopes are
  // numbered first (they are top-level), then every other node inside the segment of its scope.
  const assign = (list: Node[]): void => {
    const groups = new Map<string, Node[]>();
    for (const n of list) {
      const tid = n.name ? "" : (n.el.getAttribute("data-testid") ?? "");
      const key = `${n.scope?.segment ?? ""}|${n.role}|${n.name ? slug(n.name) : tid ? `@${tid}` : ""}`;
      groups.set(key, [...(groups.get(key) ?? []), n]);
    }
    for (const group of groups.values()) {
      group.forEach((n, i) => {
        const s = n.name ? slug(n.name) : "";
        const tid = n.el.getAttribute("data-testid") ?? "";
        const repeated = group.length > 1;
        if (s) n.segment = `${n.role}~${s}${repeated ? `#${i + 1}` : ""}`;
        else if (tid && !repeated) n.segment = `${n.role}~@${encodeURIComponent(tid)}`;
        else n.segment = `${n.role}~#${i + 1}`;
      });
    }
  };
  assign(nodes.filter((n) => isScopeKind(n.kind)));
  assign(nodes.filter((n) => !isScopeKind(n.kind)));  for (const n of nodes) {
    n.ref = `web://${originKey}/${n.scope ? `${n.scope.segment}/` : ""}${n.segment}`;
  }
  return nodes;
}

export interface Candidate {
  ref: string;
  role: string;
  name: string;
}

function candidatesOf(nodes: Node[], seg: ParsedSegment | null): Candidate[] {
  const matching = seg ? nodes.filter((n) => n.role === seg.role) : nodes;
  const closer = seg?.slug
    ? matching.filter((n) => slug(n.name) === seg.slug)
    : matching;
  return (closer.length ? closer : matching)
    .slice(0, 5)
    .map((n) => ({ ref: n.ref, role: n.role, name: n.name }));
}

/**
 * Resolves a ref against the live DOM. Exact ref first; otherwise a unique role + name match (ignoring
 * scope and index). Zero or several matches fail with TARGET_NOT_FOUND and up to 5 candidates.
 */
export function resolveRef(
  doc: Document,
  ref: string,
  originKey: string,
  nodes?: Node[],
): Node {
  const parsed = parseRef(ref);
  if (!parsed || parsed.key !== originKey) {
    throw new WyspError(
      ErrorCode.TARGET_NOT_FOUND,
      `ref is not on this origin: ${ref}`,
    );
  }
  const all = nodes ?? collectNodes(doc, originKey);
  const exact = all.find((n) => n.ref === ref);
  if (exact) return exact;
  const last = parseSegment(parsed.segments[parsed.segments.length - 1] ?? "");
  if (!last)
    throw new WyspError(ErrorCode.TARGET_NOT_FOUND, `cannot read ref: ${ref}`);
  const loose = all.filter((n) => {
    if (n.role !== last.role) return false;
    if (last.testId) return n.el.getAttribute("data-testid") === last.testId;
    return last.slug !== "" && slug(n.name) === last.slug;
  });
  if (loose.length === 1) return loose[0] as Node;
  throw new WyspError(
    ErrorCode.TARGET_NOT_FOUND,
    loose.length
      ? `ambiguous ref (${loose.length} matches): ${ref}`
      : `no element matches: ${ref}`,
    { candidates: candidatesOf(loose.length ? loose : all, last) },
  );
}
