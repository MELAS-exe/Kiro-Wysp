// LIVE driver (Playwright + Chromium): loads the built extension, points it at a Core, opens the dashboard and then
// plays "the learner" from commands that a test writes to a file. Every learner gesture is a real, trusted input
// (mouse and keyboard through the browser, so `isTrusted` is true), never `selectOption` or `dispatchEvent`.
//
//   node playwright_driver.mjs --core ws://127.0.0.1:P/ws/adapter --token-file F --page http://localhost:PORT/
//        --commands cmd.json [--seconds 150] [--serve] [--stop-file F]
//
// Protocol: the test writes {"name": ..., "args": [...]} to the commands file; the driver runs it, writes the
// outcome to <commands>.out and deletes the commands file. Without --commands the driver only holds the connection
// (contract kit launcher). --serve starts the demo dashboard on the page's port and closes it at the end; the driver
// also stops when --stop-file appears. The token is read from the file and never printed.
import {
  cpSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
};
const coreUrl = arg("core");
const token = readFileSync(arg("token-file"), "utf8").trim();
const page_url = arg("page");
const commands = arg("commands", join(tmpdir(), `wysp-pw-${process.pid}.json`));
const stopFile = arg("stop-file");
const dashboard = process.argv.includes("--serve")
  ? spawn(process.execPath, ["serve.mjs"], {
      cwd: resolve(here, "../../../demo-dashboard"),
      env: { ...process.env, PORT: new URL(page_url).port },
      stdio: "ignore",
    })
  : null;
const seconds = Number(arg("seconds", "150"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const work = mkdtempSync(join(tmpdir(), "wysp-pw-"));
const ext = join(work, "ext");
cpSync(resolve(here, "../../dist"), ext, { recursive: true });
const manifestPath = join(ext, "manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
manifest.host_permissions = [`${new URL(page_url).origin}/*`]; // optional permissions need a user gesture
writeFileSync(manifestPath, JSON.stringify(manifest));

/** The Chromium that this Playwright version expects, else the newest one already installed (or CHROMIUM). */
function chromiumPath() {
  if (process.env.CHROMIUM) return process.env.CHROMIUM;
  const expected = chromium.executablePath();
  if (existsSync(expected)) return expected;
  const base = join(process.env.LOCALAPPDATA ?? "", "ms-playwright");
  const found = existsSync(base)
    ? readdirSync(base)
        .filter((d) => /^chromium-\d+$/.test(d))
        .sort()
        .reverse()
        .map((d) => join(base, d, "chrome-win64", "chrome.exe"))
    : [];
  return found.find(existsSync) ?? expected;
}

const context = await chromium.launchPersistentContext(join(work, "profile"), {
  executablePath: chromiumPath(),
  headless: false,
  args: [
    "--headless=new",
    `--disable-extensions-except=${ext}`,
    `--load-extension=${ext}`,
  ],
});
let status = "starting";
try {
  const sw =
    context.serviceWorkers()[0] ??
    (await context.waitForEvent("serviceworker", { timeout: 15000 }));
  const id = new URL(sw.url()).host;
  const config = { coreUrl, token, allowlist: [new URL(page_url).origin] };
  for (
    let i = 0;
    i < 40 && (await sw.evaluate(() => typeof chrome?.storage)) !== "object";
    i++
  )
    await sleep(250);
  await sw.evaluate(
    (c) => chrome.storage.local.set({ "wysp.config": c }),
    config,
  );
  for (let i = 0; i < 40; i++) {
    status = await sw.evaluate(() =>
      chrome.storage.session
        .get("wysp.status")
        .then((r) => r["wysp.status"]?.status ?? null),
    );
    if (status === "connected") break;
    await sleep(500);
  }
  const page = await context.newPage();
  await page.goto(page_url);
  await page.bringToFront();
  console.log(
    JSON.stringify({ ready: status === "connected", extensionId: id }),
  );

  const region = () => page.locator("#region");
  const run = {
    /** A real click on the Region drop-down (opens the native list), then Escape to close it. */
    async click_region() {
      await region().click();
      await page.keyboard.press("Escape");
    },
    /** Real keyboard typeahead on the focused select: fires a trusted `change`. */
    async select_region(name) {
      await region().focus();
      await page.keyboard.type(String(name).slice(0, 3), { delay: 30 });
      await page.keyboard.press("Tab");
    },
    async click(selector) {
      await page.locator(selector).click();
    },
    async type_into(selector, text) {
      await page.locator(selector).click();
      await page.keyboard.type(text, { delay: 15 });
    },
    async press(key) {
      await page.keyboard.press(key);
    },
    async blur() {
      await page.locator("body").click({ position: { x: 1, y: 1 } });
    },
    async reload() {
      await page.reload();
    },
    async region_value() {
      return page.evaluate(() => document.getElementById("region").value);
    },
    async reports() {
      return page.evaluate(() =>
        [...document.querySelectorAll("#reports li")].map(
          (li) => li.textContent,
        ),
      );
    },
    async rows() {
      return page.evaluate(() =>
        [...document.querySelectorAll("#orders tbody tr")].map((tr) =>
          [...tr.cells].map((c) => c.textContent),
        ),
      );
    },
    async status() {
      return status;
    },
  };

  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline && !(stopFile && existsSync(stopFile))) {
    if (existsSync(commands)) {
      let out;
      let cmd;
      try {
        cmd = JSON.parse(readFileSync(commands, "utf8"));
      } catch {
        await sleep(30); // the file is still being written: read it again
        continue;
      }
      try {
        if (cmd.name === "quit") break;
        out = {
          ok: true,
          value: (await run[cmd.name](...(cmd.args ?? []))) ?? null,
        };
      } catch (err) {
        out = { ok: false, error: String(err?.message ?? err).slice(0, 300) };
      }
      writeFileSync(`${commands}.out`, JSON.stringify(out));
      unlinkSync(commands);
    }
    await sleep(50);
  }
} finally {
  dashboard?.kill();
  await context.close().catch(() => undefined);
  try {
    rmSync(work, { recursive: true, force: true });
  } catch {
    /* the OS temp cleanup removes what Chromium still holds */
  }
  process.exit(0);
}
