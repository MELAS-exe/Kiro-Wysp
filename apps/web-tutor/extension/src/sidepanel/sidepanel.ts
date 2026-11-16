/**
 * Side panel page. It opens the Wysp Panel served by the Core as a top-level navigation (the Panel's WebSocket
 * is origin-checked against the Core's own origin, which only holds for a page loaded from the Core itself).
 * When the Core cannot be reached or no token is set, it shows a branded explanation instead of a blank page.
 */
import { DEFAULT_CONFIG, panelTarget, type WebConfig } from "../shared/config";
import { renderFallback, type FallbackKind } from "./fallback";

const CONFIG_KEY = "wysp.config";
const PROBE_MS = 2500;
const RETRY_MS = 4000;

let retryTimer: ReturnType<typeof setTimeout> | null = null;

async function loadConfig(): Promise<WebConfig> {
  const stored = (await chrome.storage.local.get(CONFIG_KEY))[CONFIG_KEY] as
    Partial<WebConfig> | undefined;
  return {
    ...DEFAULT_CONFIG,
    ...stored,
    allowlist: stored?.allowlist ?? DEFAULT_CONFIG.allowlist,
  };
}

/** A no-cors request tells "something answers on this port" from "connection refused" without needing CORS. */
async function reachable(base: string): Promise<boolean> {
  try {
    await fetch(`${base}/`, {
      mode: "no-cors",
      cache: "no-store",
      signal: AbortSignal.timeout(PROBE_MS),
    });
    return true;
  } catch {
    return false;
  }
}

function show(kind: FallbackKind): void {
  const root = document.getElementById("root");
  if (!root) return;
  renderFallback(document, root, kind, {
    openSettings: () => void chrome.runtime.openOptionsPage(),
    retry: () => void start(),
  });
  // A Core started a moment later should just work: look again by itself while the fallback is on screen.
  if (kind === "unreachable")
    retryTimer = setTimeout(() => void start(), RETRY_MS);
}

async function start(): Promise<void> {
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  const target = panelTarget(await loadConfig());
  if (target.kind !== "ready") return show(target.kind);
  if (!(await reachable(target.base))) return show("unreachable");
  location.replace(target.url);
}

// Saving new settings while the fallback is showing re-evaluates at once.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && CONFIG_KEY in changes) void start();
});
void start();
