/**
 * In-page launcher: a small floating mascot button, bottom right, that asks the service worker to open the Wysp
 * side panel. Like the highlight overlay it lives in a CLOSED shadow root on `documentElement`, carries the
 * overlay attribute so snapshots skip it, and never touches the page's own DOM (WEB-P4 stays true).
 * Shown only on allowlisted origins (the caller decides).
 */
import { OVERLAY_ATTR } from "./a11y";
import mark from "../../public/icons/mark-64.png?inline";

export const LAUNCHER_LABEL = "Open Wysp, your tutor";
export const LAUNCHER_FALLBACK_TEXT = "Click the Wysp icon in the toolbar";
export const TOOLTIP_MS = 5000;

const STYLE = `
:host { all: initial; }
.wrap { position: fixed; right: 18px; bottom: 18px; display: flex; flex-direction: column; align-items: flex-end; gap: 8px;
  pointer-events: none; font: 13px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif; }
button { pointer-events: auto; cursor: pointer; width: 52px; height: 52px; padding: 0; border-radius: 50%;
  border: 2px solid #5440A6; background: #1D0E4A; box-shadow: 0 4px 14px rgba(13,1,47,.55); display: grid; place-items: center; }
button:hover, button:focus-visible { border-color: #CA84FC; box-shadow: 0 0 0 3px rgba(202,132,252,.35), 0 4px 14px rgba(13,1,47,.55); outline: none; }
img { width: 36px; height: 36px; display: block; }
.tip { pointer-events: none; max-width: 230px; padding: 7px 10px; border-radius: 10px; background: #1D0E4A; color: #F4E5FD;
  border: 1px solid #5440A6; box-shadow: 0 4px 14px rgba(13,1,47,.55); }
.tip[hidden] { display: none; }
@media (prefers-reduced-motion: no-preference) { button { transition: box-shadow .2s ease-out, border-color .2s ease-out; } }
`;

export class Launcher {
  private host: HTMLElement | null = null;
  private tip: HTMLElement | null = null;
  private tipTimer: ReturnType<typeof setTimeout> | null = null;

  /** `onOpen` resolves true when the side panel opened, false when the browser refused. */
  constructor(
    private readonly doc: Document,
    private readonly onOpen: () => Promise<boolean>,
    /** Tests use "open" to look inside; the product always uses "closed". */
    private readonly shadowMode: "closed" | "open" = "closed",
  ) {}

  get visible(): boolean {
    return this.host !== null;
  }

  show(): void {
    if (this.host || !this.doc.documentElement) return;
    const host = this.doc.createElement("div");
    host.setAttribute(OVERLAY_ATTR, "launcher");
    host.style.cssText =
      "position:fixed;inset:0;pointer-events:none;z-index:2147483646;";
    const root = host.attachShadow({ mode: this.shadowMode });
    const style = this.doc.createElement("style");
    style.textContent = STYLE;
    const wrap = this.doc.createElement("div");
    wrap.className = "wrap";
    const tip = this.doc.createElement("div");
    tip.className = "tip";
    tip.setAttribute("role", "status");
    tip.hidden = true;
    const button = this.doc.createElement("button");
    button.type = "button";
    button.setAttribute("aria-label", LAUNCHER_LABEL);
    button.title = LAUNCHER_LABEL;
    const img = this.doc.createElement("img");
    img.src = mark;
    img.alt = "";
    button.append(img);
    button.addEventListener("click", (ev) => {
      // Only a real click counts: the page cannot open the panel by dispatching a synthetic event.
      if (!ev.isTrusted) return;
      void this.onOpen().then((opened) => {
        if (!opened) this.say(LAUNCHER_FALLBACK_TEXT);
      });
    });
    wrap.append(tip, button);
    root.append(style, wrap);
    this.doc.documentElement.appendChild(host);
    this.host = host;
    this.tip = tip;
  }

  private say(text: string): void {
    if (!this.tip) return;
    this.tip.textContent = text;
    this.tip.hidden = false;
    if (this.tipTimer) clearTimeout(this.tipTimer);
    this.tipTimer = setTimeout(() => {
      if (this.tip) this.tip.hidden = true;
    }, TOOLTIP_MS);
  }

  hide(): void {
    if (this.tipTimer) clearTimeout(this.tipTimer);
    this.tipTimer = null;
    this.host?.remove();
    this.host = this.tip = null;
  }
}

