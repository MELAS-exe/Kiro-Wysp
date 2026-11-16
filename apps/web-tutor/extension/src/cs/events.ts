/**
 * Events: debounced state changes (MutationObserver), user actions and focus changes, with origin tagging.
 *
 * Origin: an event is `wysp` when it is synthetic (`isTrusted === false`) or when it happens inside the
 * execution window of a Wysp action (from the action until the next flush). Everything else is `user`.
 * When in doubt the event is tagged `wysp`: the learner is never credited for something Wysp did.
 */
import type { CsToSw } from "../shared/messages";
import { originAllowed } from "../shared/config";
import { OVERLAY_ATTR } from "./a11y";
import { collectNodes, type Node } from "./locators";
import { REDACTED, isSensitiveField, truncate } from "./redact";
import { buildObservation } from "./snapshot";

export type Origin = "user" | "wysp" | "unknown";

export interface TrackerDeps {
  doc: Document;
  originKey: string;
  allowlist: () => readonly string[];
  send: (message: CsToSw) => void;
  flushMs?: number;
}

const MAX_CHANGED = 50;

export class EventTracker {
  private observer: MutationObserver | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inputTimers = new Map<Element, ReturnType<typeof setTimeout>>();
  private digests = new Map<string, string>();
  private lastFocus = "";
  private executing = false;
  private readonly flushMs: number;
  private readonly listeners: Array<[string, (ev: Event) => void]> = [];

  constructor(private readonly deps: TrackerDeps) {
    this.flushMs = deps.flushMs ?? 300;
  }

  /** True while the page is on the allowlist. Checked before every message leaves the content script. */
  private allowed(): boolean {
    return originAllowed(this.deps.doc.location?.origin, this.deps.allowlist());
  }

  private emit(message: CsToSw): void {
    if (this.allowed()) this.deps.send(message);
  }

  start(): void {
    const { doc } = this.deps;
    const body = doc.body ?? doc.documentElement;
    const first = this.digest();
    this.digests = first.map;
    this.lastFocus = first.focus;
    this.observer = new MutationObserver(() => this.schedule());
    this.observer.observe(body, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
    const on = (type: string, fn: (ev: Event) => void): void => {
      doc.addEventListener(type, fn, true);
      this.listeners.push([type, fn]);
    };
    on("click", (ev) => this.userAction("click", ev));
    on("change", (ev) => this.userAction("change", ev));
    on("submit", (ev) => this.userAction("submit", ev));
    on("input", (ev) => this.debouncedInput(ev));
    on("focusin", () => this.schedule());
  }

  stop(): void {
    this.observer?.disconnect();
    this.observer = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    for (const t of this.inputTimers.values()) clearTimeout(t);
    this.inputTimers.clear();
    for (const [type, fn] of this.listeners)
      this.deps.doc.removeEventListener(type, fn, true);
    this.listeners.length = 0;
  }

  /** Called by the action dispatcher: changes until the next flush belong to Wysp. */
  markExecuting(): void {
    this.executing = true;
    this.schedule();
  }

  private originOf(ev?: Event): Origin {
    if (this.executing) return "wysp";
    if (ev && !ev.isTrusted) return "wysp";
    return "user";
  }

  private schedule(): void {
    if (this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.flush();
    }, this.flushMs);
  }

  private digest(): { map: Map<string, string>; focus: string } {
    const obs = buildObservation({ doc: this.deps.doc, originKey: this.deps.originKey, stateVersion: 0 });
    const map = new Map<string, string>();
    for (const e of obs.entities) {
      const { bbox: _volatile, ...props } = (e.props ?? {}) as Record<string, unknown>; // bbox is volatile
      map.set(e.ref, JSON.stringify([e.kind, e.label, e.parent, props]));
    }
    return { map, focus: obs.focus.join("|") };
  }

  flush(): void {
    if (!this.allowed()) return;
    const origin = this.originOf();
    const before = this.digests;
    const { map: after, focus } = this.digest();
    const changed: string[] = [];
    for (const [ref, d] of after) if (before.get(ref) !== d) changed.push(ref);
    for (const ref of before.keys()) if (!after.has(ref)) changed.push(ref);
    this.digests = after;
    const focusChanged = focus !== this.lastFocus;
    this.lastFocus = focus;
    this.executing = false;
    if (changed.length) this.emit({ wyspEvent: "state_changed", changed: changed.slice(0, MAX_CHANGED), origin });
    if (focusChanged) this.emit({ wyspEvent: "selection_changed", focus: focus ? focus.split("|") : [] });
  }
  private nodeFor(target: EventTarget | null): Node | null {
    if (!(target instanceof Element)) return null;
    const nodes = collectNodes(this.deps.doc, this.deps.originKey);
    const byEl = new Map(nodes.map((n) => [n.el, n] as const));
    for (let e: Element | null = target; e; e = e.parentElement) {
      const hit = byEl.get(e);
      if (hit) return hit;
    }
    return null;
  }

  private details(node: Node | null, ev: Event): Record<string, unknown> {
    const d: Record<string, unknown> = {};
    if (!node) return d;
    d.role = node.role;
    d.name = truncate(node.name, 80);
    const el = node.el as HTMLInputElement;
    if (ev.type === "change" || ev.type === "input") {
      if (isSensitiveField(el)) d.value = REDACTED;
      else if (/^(checkbox|radio)$/i.test(el.type ?? ""))
        d.checked = el.checked;
      else if (typeof el.value === "string") d.value = truncate(el.value);
    }
    return d;
  }

  private userAction(kind: string, ev: Event): void {
    if (!this.allowed()) return;
    // The launcher and the overlay are Wysp's own UI, not something the user did on the page.
    const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
    if (path.some((n) => n instanceof Element && n.hasAttribute(OVERLAY_ATTR))) return;
    if (ev.target instanceof Element && ev.target.closest(`[${OVERLAY_ATTR}]`)) return;
    const node = this.nodeFor(ev.target);
    this.emit({
      wyspEvent: "user_action",
      kind,
      target: node?.ref ?? null,
      details: this.details(node, ev),
      origin: this.originOf(ev),
    });
  }

  private debouncedInput(ev: Event): void {
    const target = ev.target;
    if (!(target instanceof Element)) return;
    const prior = this.inputTimers.get(target);
    if (prior) clearTimeout(prior);
    const origin = this.originOf(ev);
    this.inputTimers.set(
      target,
      setTimeout(() => {
        this.inputTimers.delete(target);
        if (!this.allowed()) return;
        const node = this.nodeFor(target);
        this.emit({
          wyspEvent: "user_action",
          kind: "input",
          target: node?.ref ?? null,
          details: this.details(node, ev),
          origin,
        });
      }, this.flushMs),
    );
  }
}



