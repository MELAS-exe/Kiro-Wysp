/**
 * Highlight overlay. A single fixed host element with a CLOSED shadow root, pointer-events none, drawn
 * above the page. It never changes the page's own DOM state and snapshots skip it (data-wysp-overlay).
 * Timed highlights end by themselves; persistent ones (duration_ms 0) stay until cleared or until the
 * user interacts with the highlighted element (then `onDismissed` fires).
 */
import { OVERLAY_ATTR } from "./a11y";

// Wysp brand: lilac glow (#CA84FC) around the target, step label on surface (#1D0E4A) with lavender text and a pink
// (#FE7C9C) accent bar. Motion is off when the user asks for reduced motion.
export const GLOW = "#CA84FC";
export const LABEL_ACCENT = "#FE7C9C";
const STYLE = `
:host { all: initial; }
.box { position: fixed; box-sizing: border-box; border: 2px solid ${GLOW}; border-radius: 10px;
  box-shadow: 0 0 0 3px rgba(202,132,252,.35), 0 0 18px 4px rgba(202,132,252,.55); pointer-events: none; }
@media (prefers-reduced-motion: no-preference) { .box.pulse { animation: wysp-pulse 1.2s ease-in-out infinite; } }
.label { position: fixed; max-width: 280px; padding: 5px 10px 5px 12px; border-radius: 10px; background: #1D0E4A; color: #F4E5FD;
  border: 1px solid #5440A6; border-left: 4px solid ${LABEL_ACCENT};
  font: 12px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif; pointer-events: none; }
@keyframes wysp-pulse { 50% { box-shadow: 0 0 0 6px rgba(202,132,252,.2), 0 0 26px 8px rgba(202,132,252,.7); } }
`;const PAD = 6;

export interface ActiveHighlight {
  ref: string;
  getEl: () => Element | null;
  durationMs: number;
}

export class Overlay {
  private host: HTMLElement | null = null;
  private box: HTMLElement | null = null;
  private labelEl: HTMLElement | null = null;
  private active: ActiveHighlight | null = null;
  private raf = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private readonly onInteract = (ev: Event): void => this.interacted(ev);

  constructor(
    private readonly doc: Document,
    private readonly onDismissed: (ref: string) => void,
  ) {}

  get current(): ActiveHighlight | null {
    return this.active;
  }

  show(h: ActiveHighlight, style: "pulse" | "outline", label?: string): void {
    this.clear();
    const el = h.getEl();
    if (!el) return;
    this.ensureHost();
    this.active = h;
    (el as HTMLElement).scrollIntoView?.({
      block: "center",
      inline: "nearest",
    });
    if (this.box) this.box.className = `box ${style}`;
    if (this.labelEl) {
      this.labelEl.textContent = label ?? "";
      this.labelEl.style.display = label ? "block" : "none";
    }
    if (h.durationMs > 0)
      this.timer = setTimeout(() => this.clear(), h.durationMs);
    else
      for (const type of ["click", "input", "change", "keydown"])
        this.doc.addEventListener(type, this.onInteract, true);
    this.loop();
  }

  /** Returns true when a highlight was showing. */
  clear(): boolean {
    const had = this.active !== null;
    this.active = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const win = this.doc.defaultView;
    if (win && this.raf) win.cancelAnimationFrame(this.raf);
    this.raf = 0;
    for (const type of ["click", "input", "change", "keydown"])
      this.doc.removeEventListener(type, this.onInteract, true);
    this.host?.remove();
    this.host = this.box = this.labelEl = null;
    return had;
  }

  private interacted(ev: Event): void {
    const a = this.active;
    if (!a || !ev.isTrusted) return; // Wysp's own synthetic events never dismiss
    const el = a.getEl();
    if (!el) return;
    const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
    if (
      path.includes(el) ||
      (ev.target instanceof Node && el.contains(ev.target))
    ) {
      const ref = a.ref;
      this.clear();
      this.onDismissed(ref);
    }
  }

  private ensureHost(): void {
    if (this.host) return;
    const host = this.doc.createElement("div");
    host.setAttribute(OVERLAY_ATTR, "");
    host.style.cssText =
      "position:fixed;inset:0;pointer-events:none;z-index:2147483647;";
    const root = host.attachShadow({ mode: "closed" });
    const style = this.doc.createElement("style");
    style.textContent = STYLE;
    const box = this.doc.createElement("div");
    box.className = "box";
    const label = this.doc.createElement("div");
    label.className = "label";
    root.append(style, box, label);
    this.doc.documentElement.appendChild(host);
    this.host = host;
    this.box = box;
    this.labelEl = label;
  }

  private loop = (): void => {
    const a = this.active;
    const win = this.doc.defaultView;
    if (!a || !win || !this.box) return;
    const el = a.getEl();
    if (el) {
      const r = el.getBoundingClientRect();
      Object.assign(this.box.style, {
        display: "block",
        left: `${r.left - PAD}px`,
        top: `${r.top - PAD}px`,
        width: `${r.width + PAD * 2}px`,
        height: `${r.height + PAD * 2}px`,
      });
      if (this.labelEl) {
        this.labelEl.style.left = `${Math.max(4, r.left - PAD)}px`;
        this.labelEl.style.top = `${Math.min(win.innerHeight - 28, r.bottom + PAD + 6)}px`;
      }
    } else {
      this.box.style.display = "none";
    }
    this.raf = win.requestAnimationFrame(this.loop);
  };
}

