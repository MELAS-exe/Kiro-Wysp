/** Content script entry. Registered only for allowlisted origins, and it re-checks the allowlist itself. */
import { DEFAULT_CONFIG } from "../shared/config";
import type { CsToSw, SwToCs } from "../shared/messages";
import { PageAgent } from "./agent";

const CONFIG_KEY = "wysp.config";

declare global {
  interface Window {
    __wyspContentScript?: boolean;
  }
}

async function main(): Promise<void> {
  if (window.top !== window || window.__wyspContentScript) return; // top frame only, once
  window.__wyspContentScript = true;

  let allowlist: readonly string[] = DEFAULT_CONFIG.allowlist;
  const stored = (await chrome.storage.local.get(CONFIG_KEY))[CONFIG_KEY] as { allowlist?: string[] } | undefined;
  if (stored?.allowlist) allowlist = stored.allowlist;

  const send = (message: CsToSw): void => {
    void chrome.runtime.sendMessage(message).catch(() => undefined);
  };
  // Called from the launcher click (a user gesture): the service worker must call sidePanel.open at once.
  const openPanel = async (): Promise<boolean> => {
    try {
      const reply = (await chrome.runtime.sendMessage({ wyspUi: "open_panel" })) as { ok?: boolean } | undefined;
      return reply?.ok === true;
    } catch {
      return false;
    }
  };
  const agent = new PageAgent(document, () => allowlist, send, openPanel);
  agent.start();

  chrome.storage.onChanged.addListener((changes, area) => {
    const change = changes[CONFIG_KEY];
    if (area !== "local" || !change) return;
    allowlist = (change.newValue as { allowlist?: string[] } | undefined)?.allowlist ?? [];
    if (!agent.allowed()) agent.stop();
    else agent.start();
  });

  chrome.runtime.onMessage.addListener((message: unknown, sender, sendResponse) => {
    if (sender.id !== chrome.runtime.id || typeof message !== "object" || message === null || !("wysp" in message)) return false;
    sendResponse(agent.handle(message as SwToCs));
    return false;
  });
}

void main();
