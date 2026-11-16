import { DEFAULT_CONFIG, isLoopbackCoreUrl, matchPattern, normalizeOrigin, panelTarget, type WebConfig } from "../shared/config";
import { describeStatus } from "./status";

const CONFIG_KEY = "wysp.config";
const STATUS_KEY = "wysp.status";
const say = (text: string): void => {
  document.getElementById("message")!.textContent = text;
};
const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

let config: WebConfig = { ...DEFAULT_CONFIG };

async function load(): Promise<void> {
  const stored = (await chrome.storage.local.get(CONFIG_KEY))[CONFIG_KEY] as Partial<WebConfig> | undefined;
  config = { ...DEFAULT_CONFIG, ...stored, allowlist: stored?.allowlist ?? DEFAULT_CONFIG.allowlist };
  $<HTMLInputElement>("core").value = config.coreUrl;
  $<HTMLInputElement>("token").value = config.token;
  await render();
}

async function render(): Promise<void> {
  const list = $("list");
  list.replaceChildren();
  for (const origin of config.allowlist) {
    const granted = await chrome.permissions.contains({ origins: [matchPattern(origin)] });
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = origin;
    const state = document.createElement("em");
    state.className = granted ? "ok" : "warn";
    state.textContent = granted ? "allowed" : "permission needed";
    const grant = document.createElement("button");
    grant.type = "button";
    grant.textContent = "Grant";
    grant.hidden = granted;
    grant.addEventListener("click", () => void chrome.permissions.request({ origins: [matchPattern(origin)] }).then(render));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      config.allowlist = config.allowlist.filter((o) => o !== origin);
      void chrome.permissions.remove({ origins: [matchPattern(origin)] }).finally(() => void save());
    });
    li.append(label, state, grant, remove);
    list.append(li);
  }
}

async function save(): Promise<void> {
  const core = $<HTMLInputElement>("core").value.trim();
  if (!isLoopbackCoreUrl(core)) {
    say("The Core address must be a ws:// URL on 127.0.0.1 or localhost.");
    return;
  }
  config = { ...config, coreUrl: core, token: $<HTMLInputElement>("token").value.trim() };
  await chrome.storage.local.set({ [CONFIG_KEY]: config });
  say("Saved.");
  await render();
}

$("add").addEventListener("click", () => {
  const origin = normalizeOrigin($<HTMLInputElement>("origin").value);
  if (!origin) {
    say("Enter an http(s) origin such as https://example.com.");
    return;
  }
  // chrome.permissions.request must run from this click (a user gesture), so it is the first call.
  void chrome.permissions.request({ origins: [matchPattern(origin)] }).then(async (granted) => {
    if (granted && !config.allowlist.includes(origin)) config.allowlist = [...config.allowlist, origin];
    $<HTMLInputElement>("origin").value = "";
    await save();
  });
});

$("form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  void save();
});

function showStatus(value: unknown): void {
  const s = value as { status?: string; detail?: string } | undefined;
  const view = describeStatus(s?.status, s?.detail);
  $("status-card").dataset.tone = view.tone;
  $("status-headline").textContent = view.headline;
  $("status-advice").textContent = view.advice;
}

/** "Open Wysp": the side panel when Chrome allows it (this click is a user gesture), else the Panel in a new tab. */
async function openWysp(): Promise<void> {
  const hint = $("open-hint");
  try {
    const win = await chrome.windows.getCurrent();
    await chrome.sidePanel.open({ windowId: win.id as number });
    hint.textContent = "The Wysp panel is open on the side of this window.";
  } catch {
    const target = panelTarget(config);
    if (target.kind === "ready") {
      await chrome.tabs.create({ url: target.url });
      hint.textContent = "Chrome did not open the side panel, so Wysp opened in a new tab. Or click the Wysp icon in the toolbar.";
    } else {
      hint.textContent = "Save a valid Core address and pairing token first, then try again.";
    }
  }
}
$("open-wysp").addEventListener("click", () => void openWysp());

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes[STATUS_KEY]) showStatus(changes[STATUS_KEY].newValue);
});
chrome.permissions.onAdded.addListener(() => void render());
void chrome.storage.session.get(STATUS_KEY).then((r) => showStatus(r[STATUS_KEY]));
void load();
