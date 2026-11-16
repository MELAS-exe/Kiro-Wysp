// LIVE check of the user-facing parts (launcher, options, side panel page, overlay, dashboard). Not part of `npm test`.
// Runs a Playwright Chromium with the built extension against a SECOND Core, so a running session is never touched.
//
//   $env:WYSP_PW_DIR = "<dir where `npm i playwright-core` was run>"
//   node tests/live/panel_access_check.mjs --core-port 8799 --token-file <WYSP_HOME>/token --page http://localhost:5181/ --out docs/img
//
// The Core must be started with WYSP_ALLOWED_ORIGINS=chrome-extension://cnmikeniefgoeibijogfncggjkafakhk.
// The optional host permission cannot be granted without a user gesture, so the test copies dist/ and adds the
// page origin to host_permissions (the manifest key, and so the extension id, stay the same). The token is never printed.
import { cpSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
};
const port = arg("core-port", "8799");
const page = arg("page", "http://localhost:5181/");
const out = resolve(arg("out", "docs/img"));
const token = readFileSync(arg("token-file"), "utf8").trim();
const chromePath = process.env.CHROME; // optional: a specific chrome.exe
const require = createRequire(join(process.env.WYSP_PW_DIR ?? process.cwd(), "x.js"));
const { chromium } = require("playwright-core");

const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

mkdirSync(out, { recursive: true });
const work = mkdtempSync(join(tmpdir(), "wysp-pw-"));
const ext = join(work, "ext");
cpSync(resolve(here, "../../dist"), ext, { recursive: true });
const mpath = join(ext, "manifest.json");
const manifest = JSON.parse(readFileSync(mpath, "utf8"));
manifest.host_permissions = [`${new URL(page).origin}/*`];
writeFileSync(mpath, JSON.stringify(manifest));

const ctx = await chromium.launchPersistentContext(join(work, "profile"), {
  headless: false,
  executablePath: chromePath || undefined,
  viewport: { width: 1200, height: 800 },
  args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`, "--headless=new"],
});
try {
  let sw = ctx.serviceWorkers()[0] ?? (await ctx.waitForEvent("serviceworker", { timeout: 15000 }));
  const id = new URL(sw.url()).host;
  console.log(`extension id ${id}`);
  check("extension id is the pinned one", id === "cnmikeniefgoeibijogfncggjkafakhk");

  const setConfig = (cfg) =>
    sw.evaluate((c) => chrome.storage.local.set({ "wysp.config": c }), cfg);
  const good = {
    coreUrl: `ws://127.0.0.1:${port}/ws/adapter`,
    token,
    allowlist: [new URL(page).origin],
  };
  await setConfig(good);
  await sleep(3000); // the service worker registers the content script for the allowed origin

  // 1. Dashboard + launcher
  const tab = await ctx.newPage();
  await tab.setViewportSize({ width: 1200, height: 800 });
  await tab.goto(page);
  await sleep(2500);
  await tab.screenshot({ path: join(out, "web-tutor-dashboard-launcher.png") });
  // The launcher lives in a closed shadow root: look at pixels instead of the DOM. It sits bottom right.
  const snapshot = await tab.evaluate(() => ({
    overlayHosts: document.querySelectorAll("[data-wysp-overlay]").length,
    bodyHasWysp: document.body.innerHTML.includes("Open Wysp"),
  }));
  check("launcher host present (outside <body>)", snapshot.overlayHosts === 1 && !snapshot.bodyHasWysp);

  // 2. Connection status in the options page
  const options = await ctx.newPage();
  await options.setViewportSize({ width: 900, height: 900 });
  await options.goto(`chrome-extension://${id}/options.html`);
  await sleep(1500);
  const headline = await options.textContent("#status-headline");
  check("options shows the connection as connected", /^Connected/.test(headline ?? ""), headline ?? "");
  await options.screenshot({ path: join(out, "web-tutor-options.png"), fullPage: true });

  // 3. Side panel page loads the Panel, and the Panel lists the web adapter
  const side = await ctx.newPage();
  await side.setViewportSize({ width: 420, height: 800 });
  await side.goto(`chrome-extension://${id}/sidepanel.html`);
  await side.waitForURL(new RegExp(`^http://127\\.0\\.0\\.1:${port}/`), { timeout: 15000 }).catch(() => {});
  const url = side.url();
  check("side panel page navigated to the Core Panel", url.startsWith(`http://127.0.0.1:${port}/`), url.replace(/#.*/, ""));
  check("token fragment was removed from the address", !url.includes("wysp_token"));
  await sleep(2500);
  const dot = await side.getAttribute(".dot", "aria-label").catch(() => null);
  check("Panel is connected to the Core", /^Wysp is /.test(dot ?? ""), dot ?? "no status dot");
  await side.click('button[aria-label="Menu"]').catch(() => {});
  const adapters = await side.$$eval('select[aria-label="Application the tutor is looking at"] option', (o) => o.map((x) => x.textContent)).catch(() => []);
  check("Panel menu lists the browser adapter", adapters.some((t) => /Chrome/.test(t ?? "")), JSON.stringify(adapters));
  await side.screenshot({ path: join(out, "web-tutor-sidepanel.png") });

  // 4. Fallback page: no token
  await setConfig({ ...good, token: "" });
  const fb = await ctx.newPage();
  await fb.setViewportSize({ width: 420, height: 800 });
  await fb.goto(`chrome-extension://${id}/sidepanel.html`);
  await sleep(800);
  check("fallback shows the settings button without a token", (await fb.textContent("#open-settings").catch(() => "")) === "Open Wysp settings");
  await fb.screenshot({ path: join(out, "web-tutor-sidepanel-fallback.png") });
  // Core unreachable
  await setConfig({ ...good, coreUrl: "ws://127.0.0.1:1/ws/adapter" });
  await sleep(1500);
  check("fallback says the Core is unreachable", ((await fb.textContent("h1").catch(() => "")) ?? "").includes("can't reach"));
  await fb.close();
  await setConfig(good);
  await sleep(2500);

  // 5. Highlight overlay (message the content script like the service worker does)
  await tab.bringToFront();
  const ref = `web://${new URL(page).host}/region~filters/combobox~region`;
  const reply = await sw.evaluate(async ([r]) => {
    const [t] = await chrome.tabs.query({ active: true, url: "http://localhost:5181/*" });
    return chrome.tabs.sendMessage(t.id, { wysp: "highlight", ref: r, style: "pulse", durationMs: 0, label: "Pick Transylvania here" });
  }, [ref]);
  check("highlight accepted by the content script", reply?.ok === true, JSON.stringify(reply).slice(0, 80));
  await sleep(500);
  await tab.screenshot({ path: join(out, "web-tutor-highlight.png") });

  // 6. Launcher click: a real mouse click. Headless Chrome has no side panel UI, so a refusal shows the tooltip.
  await sw.evaluate(() => chrome.tabs.query({ active: true, url: "http://localhost:5181/*" }).then(([t]) => chrome.tabs.sendMessage(t.id, { wysp: "clear_highlight" })));
  await sw.evaluate(() => {
    const orig = chrome.sidePanel.open.bind(chrome.sidePanel);
    globalThis.__calls = [];
    chrome.sidePanel.open = (o) => {
      globalThis.__calls.push(`open:${JSON.stringify(Object.keys(o))}`);
      return orig(o).then((r) => (globalThis.__calls.push("ok"), r), (e) => (globalThis.__calls.push(`err:${e.message}`), Promise.reject(e)));
    };
  });
  await tab.mouse.click(1200 - 18 - 26, 800 - 18 - 26);
  await sleep(1200);
  const calls = await sw.evaluate(() => globalThis.__calls);
  check("launcher click reached sidePanel.open with a tabId", calls.some((c) => c.startsWith("open:") && c.includes("tabId")), JSON.stringify(calls));
  await tab.screenshot({ path: join(out, "web-tutor-launcher-click.png") });
} finally {
  await ctx.close();
}
const failed = results.filter((r) => !r.ok);
console.log(failed.length ? `${failed.length} check(s) failed` : "all checks passed");
process.exit(failed.length ? 1 : 0);


