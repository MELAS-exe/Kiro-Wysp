/**
 * Service worker: owns the WebSocket to the Core (heartbeat, reconnect), tracks the active allowlisted tab,
 * and routes adapter.* requests to that tab's content script. It keeps no state only in memory: the worker
 * can be killed at any time, and the next event re-runs this script, which reconnects and says hello again.
 */
import {
  AdapterClient,
  ErrorCode,
  WyspError,
  type ActionCall,
  type ActionResult,
  type Observation,
} from "@wysp/adapter-sdk";
import { CATALOG, actionSpecs } from "../actions/index";
import {
  DEFAULT_CONFIG,
  isLoopbackCoreUrl,
  matchPattern,
  normalizeOrigin,
  originAllowed,
  type WebConfig,
} from "../shared/config";
import type {
  CsActionOutcome,
  CsReply,
  CsToSw,
  SwToCs,
} from "../shared/messages";
import { buildManifest } from "./manifest";
import {
  CONFIG_STORAGE_KEY,
  bumpVersion,
  currentVersion,
  lastTab,
  loadConfig,
  rememberTab,
  saveUndo,
  setStatus,
  takeUndo,
  warmVersion,
} from "./state";

const SCRIPT_ID = "wysp-cs";
const KEEPALIVE = "wysp-keepalive";

let client: AdapterClient | null = null;
let config: WebConfig = DEFAULT_CONFIG;

// ------------------------------------------------------------------------------------------ tabs
async function allowlistedTabs(): Promise<chrome.tabs.Tab[]> {
  const active = await chrome.tabs.query({ active: true });
  const focused = await chrome.tabs.query({
    active: true,
    lastFocusedWindow: true,
  });
  const focusedIds = new Set(focused.map((t) => t.id));
  return active
    .filter((t) => t.id !== undefined && originAllowed(t.url, config.allowlist))
    .sort(
      (a, b) => Number(focusedIds.has(b.id)) - Number(focusedIds.has(a.id)),
    );
}

async function activeTabId(): Promise<number | null> {
  const tabs = await allowlistedTabs();
  const id = tabs[0]?.id;
  if (id !== undefined) {
    await rememberTab(id);
    return id;
  }
  return null;
}

async function toTab(tabId: number, msg: SwToCs): Promise<CsReply> {
  const send = (): Promise<CsReply> =>
    chrome.tabs.sendMessage(tabId, msg) as Promise<CsReply>;
  try {
    return await send();
  } catch {
    // The page was open before the script was registered: inject the packaged content script once.
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ["content.js"],
      });
      return await send();
    } catch {
      throw new WyspError(
        ErrorCode.TARGET_NOT_FOUND,
        "the page is not reachable (reload it, or allow the site in the options)",
      );
    }
  }
}

function unwrap<T>(reply: CsReply): T {
  if (!reply.ok) throw new WyspError(reply.code, reply.message, reply.data);
  return reply.result as T;
}

// ---------------------------------------------------------------------------------------- handler
function emptyObservation(stateVersion: number): Observation {
  return {
    observation_id: crypto.randomUUID(),
    state_version: stateVersion,
    captured_at: new Date().toISOString(),
    scope: { level: "focus", root: null, depth: null },
    entities: [],
    links: [],
    focus: [],
    truncated: false,
    counts: { not_allowed: 1 },
  };
}

async function handle(
  method: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  switch (method) {
    case "adapter.get_actions":
      return actionSpecs();
    case "adapter.observe": {
      const tab = await activeTabId();
      if (tab === null) return emptyObservation(currentVersion());
      const obs = unwrap<Observation>(
        await toTab(tab, { wysp: "observe", scope: params.scope as never }),
      );
      return { ...obs, state_version: currentVersion() };
    }
    case "adapter.get_context": {
      const tab = await activeTabId();
      if (tab === null) {
        return {
          summary: "No allowlisted page is active, so nothing is read.",
          facts: { not_allowed: true },
          focus: [],
        };
      }
      return unwrap(await toTab(tab, { wysp: "context" }));
    }
    case "adapter.execute":
      return execute((params.call ?? params) as Partial<ActionCall>);
    case "adapter.undo":
      return undo(String(params.token ?? ""));
    case "adapter.highlight": {
      const tab = await activeTabId();
      if (tab === null)
        throw new WyspError(
          ErrorCode.TARGET_NOT_FOUND,
          "no allowlisted page is active",
        );
      const style = params.style === "outline" ? "outline" : "pulse";
      const duration =
        typeof params.duration_ms === "number" ? params.duration_ms : 2500;
      unwrap(
        await toTab(tab, {
          wysp: "highlight",
          ref: String(params.ref),
          style,
          durationMs: duration,
        }),
      );
      return { ok: true };
    }
    case "adapter.clear_highlight": {
      const tab = await activeTabId();
      if (tab === null) return { cleared: false };
      return unwrap(await toTab(tab, { wysp: "clear_highlight" }));
    }
    case "adapter.verify":
      throw new WyspError(
        ErrorCode.NOT_SUPPORTED,
        "verify.native is not offered by this adapter",
      );
    default:
      throw new WyspError(
        ErrorCode.METHOD_NOT_FOUND,
        `unknown method: ${method}`,
      );
  }
}

async function execute(call: Partial<ActionCall>): Promise<ActionResult> {
  if (typeof call.action_id !== "string")
    throw new WyspError(ErrorCode.INVALID_PARAMS, "action_id is required");
  if (!CATALOG.has(call.action_id))
    throw new WyspError(
      ErrorCode.ACTION_NOT_FOUND,
      `unknown action: ${call.action_id}`,
    );
  const params = (call.params ?? {}) as Record<string, unknown>;
  const dryRun = call.dry_run === true;
  const tab = await activeTabId();
  if (tab === null)
    throw new WyspError(
      ErrorCode.PRECONDITION_FAILED,
      "no allowlisted page is active",
    );
  const outcome = unwrap<CsActionOutcome>(
    await toTab(tab, {
      wysp: "execute",
      actionId: call.action_id,
      params,
      dryRun,
    }),
  );
  let undoToken: string | null = null;
  if (!dryRun && outcome.undo) {
    undoToken = crypto.randomUUID();
    await saveUndo(undoToken, tab, outcome.undo);
  }
  const version = dryRun ? currentVersion() : await bumpVersion();
  return {
    status: outcome.status,
    state_version: version,
    changed: outcome.changed,
    undo_token: undoToken,
    message: outcome.message ?? null,
    preview: (outcome.preview ?? null) as ActionResult["preview"],
  };
}

async function undo(token: string): Promise<ActionResult> {
  const stored = await takeUndo(token);
  if (!stored)
    throw new WyspError(
      ErrorCode.UNDO_UNAVAILABLE,
      "unknown or expired undo token",
    );
  const outcome = unwrap<CsActionOutcome>(
    await toTab(stored.tabId, { wysp: "undo", record: stored.record }),
  );
  return {
    status: "ok",
    state_version: await bumpVersion(),
    changed: outcome.changed,
    message: "Undone.",
  };
}

// ----------------------------------------------------------------------------------------- events
async function forward(message: CsToSw): Promise<void> {
  if (!client) return;
  switch (message.wyspEvent) {
    case "state_changed":
      client.notify("event.state_changed", {
        state_version: await bumpVersion(),
        changed: message.changed,
        origin: message.origin,
      });
      break;
    case "selection_changed":
      client.notify("event.selection_changed", { focus: message.focus });
      break;
    case "user_action":
      client.notify("event.user_action", {
        kind: message.kind,
        target: message.target,
        details: message.details,
        origin: message.origin,
      });
      break;
    case "highlight_dismissed":
      client.notify("event.highlight_dismissed", {
        ref: message.ref,
        reason: "user",
      });
      break;
  }
}

chrome.runtime.onMessage.addListener((message: unknown, sender, sendResponse) => {
  if (
    sender.id !== chrome.runtime.id ||
    !sender.tab ||
    typeof message !== "object" ||
    message === null
  )
    return false;
  // Events and panel requests only count from allowlisted pages (the content script checks too).
  if (!originAllowed(sender.tab.url, config.allowlist)) return false;
  if ("wyspUi" in message) {
    // The launcher click is a user gesture: sidePanel.open must be the first thing done here (no await before it).
    const tabId = sender.tab.id;
    if ((message as { wyspUi?: unknown }).wyspUi !== "open_panel" || tabId === undefined) {
      sendResponse({ ok: false });
      return false;
    }
    chrome.sidePanel.open({ tabId }).then(
      () => sendResponse({ ok: true }),
      () => sendResponse({ ok: false }),
    );
    return true; // the response is sent asynchronously
  }
  if (!("wyspEvent" in message)) return false;
  void forward(message as CsToSw);
  return false;
});
async function onNavigation(details: {
  tabId: number;
  frameId: number;
  url: string;
}): Promise<void> {
  if (
    details.frameId !== 0 ||
    !client ||
    !originAllowed(details.url, config.allowlist)
  )
    return;
  const url = new URL(details.url);
  const tab = await chrome.tabs.get(details.tabId).catch(() => undefined);
  // Query string and fragment are dropped: they can carry tokens.
  client.notify("event.navigation", {
    url: url.origin + url.pathname,
    title: (tab?.title ?? "").slice(0, 200),
  });
}
chrome.webNavigation.onHistoryStateUpdated.addListener(
  (d) => void onNavigation(d),
);
chrome.webNavigation.onCompleted.addListener((d) => void onNavigation(d));

// -------------------------------------------------------------------------------- content scripts
/** Registers the content script only for allowlisted origins whose host permission was granted. */
async function syncContentScripts(): Promise<void> {
  const granted: string[] = [];
  for (const origin of config.allowlist) {
    const normalized = normalizeOrigin(origin);
    if (
      normalized &&
      (await chrome.permissions.contains({
        origins: [matchPattern(normalized)],
      }))
    )
      granted.push(matchPattern(normalized));
  }
  const existing = await chrome.scripting.getRegisteredContentScripts({
    ids: [SCRIPT_ID],
  });
  if (existing.length)
    await chrome.scripting.unregisterContentScripts({ ids: [SCRIPT_ID] });
  if (!granted.length) return;
  await chrome.scripting.registerContentScripts([
    {
      id: SCRIPT_ID,
      js: ["content.js"],
      matches: granted,
      runAt: "document_idle",
      persistAcrossSessions: true,
    },
  ]);
}

// ------------------------------------------------------------------------------------- connection
async function connect(): Promise<void> {
  config = await loadConfig();
  await warmVersion();
  client?.stop();
  client = null;
  if (!config.token) {
    await setStatus("no_token", "Paste the pairing token in the options page.");
    return;
  }
  if (!isLoopbackCoreUrl(config.coreUrl)) {
    await setStatus(
      "bad_url",
      "The Core URL must be a loopback address (127.0.0.1).",
    );
    return;
  }
  client = new AdapterClient({
    manifest: buildManifest(
      navigator.userAgent.match(/Chrome\/([\d.]+)/)?.[1] ?? "unknown",
    ),
    url: config.coreUrl,
    token: config.token,
    handler: handle,
    heartbeatMs: 15_000,
    stateVersion: currentVersion,
    onStatus: (status, detail) => void setStatus(status, detail),
  });
  client.start();
}

let connecting = false;
let reconnectAgain = false;
/**
 * (Re)connects with the current settings. Wake-up events can arrive together on a worker start, and the
 * settings can change while a connect is in flight: run one at a time and run once more if asked meanwhile.
 */
async function boot(): Promise<void> {
  if (connecting) {
    reconnectAgain = true;
    return;
  }
  connecting = true;
  try {
    do {
      reconnectAgain = false;
      await connect();
    } while (reconnectAgain);
  } finally {
    connecting = false;
  }
  void syncContentScripts().catch(() => undefined); // never blocks the connection
}
/** The toolbar icon opens the side panel (the panel page is set in the manifest). */
function enableToolbarPanel(): void {
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => undefined);
}
enableToolbarPanel();

chrome.runtime.onInstalled.addListener((details) => {
  enableToolbarPanel();
  void boot();
  if (details.reason === "install") void chrome.runtime.openOptionsPage();
});
chrome.runtime.onStartup.addListener(() => void boot());
chrome.permissions.onAdded.addListener(() => void syncContentScripts());
chrome.permissions.onRemoved.addListener(() => void syncContentScripts());
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && CONFIG_STORAGE_KEY in changes) void boot();
});
// A wake-up every 30 s revives a worker that Chrome stopped while the socket was down.
chrome.alarms.create(KEEPALIVE, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === KEEPALIVE && (!client || client.status === "stopped"))
    void boot();
});

void boot(); // every worker start (including restarts) reconnects and sends wysp.hello again

