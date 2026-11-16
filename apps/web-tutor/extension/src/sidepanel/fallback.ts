/** The branded page the side panel shows when it cannot open the Wysp Panel (never a blank page). */

export type FallbackKind = "no_token" | "bad_token" | "bad_url" | "unreachable";

export interface FallbackContent {
  title: string;
  message: string;
  steps: string[];
  /** Whether a "Try again" button makes sense (the Core may simply not be running yet). */
  retry: boolean;
}

export const FALLBACKS: Record<FallbackKind, FallbackContent> = {
  no_token: {
    title: "Let's connect Wysp",
    message:
      "Wysp needs the pairing token of your local Core before it can open the tutor.",
    steps: [
      "Open the settings.",
      "Paste the contents of ~/.wysp/token.",
      "Press Save. This panel opens the tutor by itself.",
    ],
    retry: false,
  },
  bad_token: {
    title: "That token looks wrong",
    message:
      "The pairing token may only contain letters, digits, dots, dashes and underscores.",
    steps: [
      "Open the settings.",
      "Paste the token again, without spaces or quotes.",
      "Press Save.",
    ],
    retry: false,
  },
  bad_url: {
    title: "The Core address is not allowed",
    message:
      "Wysp only talks to a Core on this computer (127.0.0.1 or localhost).",
    steps: [
      "Open the settings.",
      "Set the Core address to ws://127.0.0.1:8765/ws/adapter.",
      "Press Save.",
    ],
    retry: false,
  },
  unreachable: {
    title: "I can't reach the Wysp Core",
    message:
      "The tutor runs on your computer, and it does not seem to be running.",
    steps: ["Start it with: uv run wysp serve", "Then press Try again."],
    retry: true,
  },
};

export interface FallbackActions {
  openSettings: () => void;
  retry: () => void;
}

/** Renders the fallback into `root` (replacing its content). Pure DOM code, tested with happy-dom. */
export function renderFallback(
  doc: Document,
  root: HTMLElement,
  kind: FallbackKind,
  actions: FallbackActions,
): void {
  const c = FALLBACKS[kind];
  const wrap = doc.createElement("main");
  wrap.className = "fallback";
  wrap.setAttribute("aria-labelledby", "fallback-title");

  const img = doc.createElement("img");
  img.src = "icons/icon-128.png";
  img.alt = "Wysp, a small violet flame with round glasses";
  img.width = 96;
  img.height = 96;
  img.className = "mascot float";

  const h1 = doc.createElement("h1");
  h1.id = "fallback-title";
  h1.textContent = c.title;

  const p = doc.createElement("p");
  p.className = "muted";
  p.textContent = c.message;

  const ol = doc.createElement("ol");
  for (const step of c.steps) {
    const li = doc.createElement("li");
    li.textContent = step;
    ol.append(li);
  }

  const row = doc.createElement("div");
  row.className = "row";
  const settings = doc.createElement("button");
  settings.type = "button";
  settings.id = "open-settings";
  settings.className = "primary";
  settings.textContent = "Open Wysp settings";
  settings.addEventListener("click", actions.openSettings);
  row.append(settings);
  if (c.retry) {
    const retry = doc.createElement("button");
    retry.type = "button";
    retry.id = "retry";
    retry.textContent = "Try again";
    retry.addEventListener("click", actions.retry);
    row.append(retry);
  }

  const status = doc.createElement("p");
  status.id = "fallback-status";
  status.className = "muted";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");

  wrap.append(img, h1, p, ol, row, status);
  root.replaceChildren(wrap);
}

