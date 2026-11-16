// LIVE check (needs Chrome and a running Core): loads the built extension in a throw-away Chrome profile,
// configures it, and reports whether the adapter connects to the Core. Not part of `npm test`.
//
//   node tests/live/live_check.mjs --core ws://127.0.0.1:8765/ws/adapter --token-file <path> [--page http://localhost:5180/] [--hold 0]
//
// Chrome 137+ ignores --load-extension, so the extension is loaded through the DevTools pipe
// (Extensions.loadUnpacked, needs --enable-unsafe-extension-debugging). Optional host permissions cannot be
// granted without a user gesture, so the test copies dist/ and adds the page origin as a host permission.
// The token is read from the file and never printed.
import { spawn } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
};
const coreUrl = arg("core", "ws://127.0.0.1:8765/ws/adapter");
const tokenFile = arg("token-file");
const page = arg("page", "http://localhost:5180/");
const holdMs = Number(arg("hold", "0")) * 1000;
const chrome = process.env.CHROME ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
if (!tokenFile) throw new Error("--token-file is required");
const token = readFileSync(tokenFile, "utf8").trim();

const work = mkdtempSync(join(tmpdir(), "wysp-live-"));
const ext = join(work, "ext");
cpSync(resolve(here, "../../dist"), ext, { recursive: true });
const manifestPath = join(ext, "manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
manifest.host_permissions = [`${new URL(page).origin}/*`];
writeFileSync(manifestPath, JSON.stringify(manifest));

const proc = spawn(
  chrome,
  ["--remote-debugging-pipe", "--enable-unsafe-extension-debugging", `--user-data-dir=${join(work, "profile")}`,
    "--no-first-run", "--no-default-browser-check", "--headless=new", "about:blank"],
  { stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"] },
);
const toChrome = proc.stdio[3];
const fromChrome = proc.stdio[4];
let nextId = 1;
const pending = new Map();
let buffer = "";
fromChrome.on("data", (chunk) => {
  buffer += chunk.toString("utf8");
  let nul;
  while ((nul = buffer.indexOf("\0")) >= 0) {
    const msg = JSON.parse(buffer.slice(0, nul));
    buffer = buffer.slice(nul + 1);
    if (msg.id && pending.has(msg.id)) {
      const { resolve: ok, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(`${msg.error.message}`)) : ok(msg.result);
    }
  }
});
const cdp = (method, params = {}, sessionId) =>
  new Promise((ok, reject) => {
    const id = nextId++;
    pending.set(id, { resolve: ok, reject });
    toChrome.write(`${JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) })}\0`);
  });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const report = { loaded: false, connected: false };

async function swSession(id) {
  for (let i = 0; i < 40; i++) {
    const { targetInfos } = await cdp("Target.getTargets");
    const sw = targetInfos.find((t) => t.type === "service_worker" && t.url.startsWith(`chrome-extension://${id}/`));
    if (sw) return (await cdp("Target.attachToTarget", { targetId: sw.targetId, flatten: true })).sessionId;
    await sleep(250);
  }
  throw new Error("extension service worker did not start");
}
const evalIn = async (sessionId, expression) => {
  const r = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId);
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? "evaluation failed");
  return r.result.value;
};

try {
  const { id } = await cdp("Extensions.loadUnpacked", { path: ext });
  report.loaded = true;
  report.extensionId = id;
  const sw = await swSession(id);
  await cdp("Runtime.enable", {}, sw);
  for (let i = 0; i < 40 && (await evalIn(sw, "typeof globalThis.chrome?.storage")) !== "object"; i++) await sleep(250); // the worker global is ready slightly after the target appears
  const config = JSON.stringify({ coreUrl, token, allowlist: [new URL(page).origin] });
  await evalIn(sw, `chrome.storage.local.set({"wysp.config": ${config}}).then(() => true)`);
  for (let i = 0; i < 40 && !report.connected; i++) {
    await sleep(500);
    const s = await evalIn(sw, `chrome.storage.session.get("wysp.status").then(r => r["wysp.status"] ?? null)`);
    report.status = s?.status;
    report.detail = s?.detail;
    report.connected = s?.status === "connected";
  }
  if (report.connected) {
    const { targetId } = await cdp("Target.createTarget", { url: page });
    await sleep(2500);
    report.pageOpened = Boolean(targetId);
    const scripts = await evalIn(sw, `chrome.scripting.getRegisteredContentScripts().then(r => r.map(s => ({id: s.id, matches: s.matches})))`);
    report.contentScripts = scripts;
    if (holdMs) {
      console.log(JSON.stringify({ ...report, holding_s: holdMs / 1000 }));
      await sleep(holdMs);
    }
  }
} catch (err) {
  report.error = String(err.message ?? err);
} finally {
  console.log(JSON.stringify(report, null, 2));
  proc.kill();
  await sleep(500);
  try {
    rmSync(work, { recursive: true, force: true });
  } catch {
    /* Chromium may still hold files; the OS temp cleanup removes them */
  }
  process.exit(report.connected ? 0 : 1);
}
