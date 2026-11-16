/** Service worker state that must survive a worker restart lives in chrome.storage.session, never only in memory. */
import { DEFAULT_CONFIG, type WebConfig } from "../shared/config";
import type { UndoRecord } from "../shared/messages";

const CONFIG_KEY = "wysp.config";
const VERSION_KEY = "wysp.stateVersion";
const UNDO_KEY = "wysp.undo";
const TAB_KEY = "wysp.lastTab";
export const STATUS_KEY = "wysp.status";
const MAX_UNDO = 50;

export async function loadConfig(): Promise<WebConfig> {
  const stored = (await chrome.storage.local.get(CONFIG_KEY))[CONFIG_KEY] as
    Partial<WebConfig> | undefined;
  return {
    ...DEFAULT_CONFIG,
    ...stored,
    allowlist: stored?.allowlist ?? DEFAULT_CONFIG.allowlist,
  };
}

export async function saveConfig(config: WebConfig): Promise<void> {
  await chrome.storage.local.set({ [CONFIG_KEY]: config });
}

export const CONFIG_STORAGE_KEY = CONFIG_KEY;

let version: number | null = null;
let chain: Promise<unknown> = Promise.resolve();

async function readVersion(): Promise<number> {
  if (version === null)
    version = Number(
      (await chrome.storage.session.get(VERSION_KEY))[VERSION_KEY] ?? 0,
    );
  return version;
}

export function currentVersion(): number {
  return version ?? 0;
}

export async function warmVersion(): Promise<void> {
  await readVersion();
}

/** Strictly increasing across worker restarts. Calls are serialized so concurrent bumps cannot collide. */
export function bumpVersion(): Promise<number> {
  const next = chain.then(async () => {
    const v = (await readVersion()) + 1;
    version = v;
    await chrome.storage.session.set({ [VERSION_KEY]: v });
    return v;
  });
  chain = next.catch(() => undefined);
  return next;
}

interface StoredUndo {
  tabId: number;
  record: UndoRecord;
}

export async function saveUndo(
  token: string,
  tabId: number,
  record: UndoRecord,
): Promise<void> {
  const all = ((await chrome.storage.session.get(UNDO_KEY))[UNDO_KEY] ??
    {}) as Record<string, StoredUndo>;
  all[token] = { tabId, record };
  const keys = Object.keys(all);
  for (const old of keys.slice(0, Math.max(0, keys.length - MAX_UNDO)))
    delete all[old];
  await chrome.storage.session.set({ [UNDO_KEY]: all });
}

export async function takeUndo(token: string): Promise<StoredUndo | null> {
  const all = ((await chrome.storage.session.get(UNDO_KEY))[UNDO_KEY] ??
    {}) as Record<string, StoredUndo>;
  const hit = all[token];
  if (!hit) return null;
  delete all[token];
  await chrome.storage.session.set({ [UNDO_KEY]: all });
  return hit;
}

export async function rememberTab(tabId: number): Promise<void> {
  await chrome.storage.session.set({ [TAB_KEY]: tabId });
}

export async function lastTab(): Promise<number | null> {
  const v = (await chrome.storage.session.get(TAB_KEY))[TAB_KEY];
  return typeof v === "number" ? v : null;
}

export async function setStatus(
  status: string,
  detail?: string,
): Promise<void> {
  await chrome.storage.session.set({
    [STATUS_KEY]: { status, detail: detail ?? "", at: Date.now() },
  });
}
