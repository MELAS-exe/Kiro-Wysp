import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PageAgent } from "../src/cs/agent";
import {
  LAUNCHER_FALLBACK_TEXT,
  LAUNCHER_LABEL,
  Launcher,
} from "../src/cs/launcher";
import { buildObservation } from "../src/cs/snapshot";
import { describeStatus } from "../src/options/status";
import {
  DEFAULT_CONFIG,
  coreHttpBase,
  panelTarget,
} from "../src/shared/config";
import {
  FALLBACKS,
  renderFallback,
  type FallbackKind,
} from "../src/sidepanel/fallback";
import { KEY, dashboardBody, setPage, stable, trusted } from "./util";
import type { CsToSw } from "../src/shared/messages";

const here = dirname(fileURLToPath(import.meta.url));
const ext = join(here, "..");
const read = (p: string): string => readFileSync(join(ext, p), "utf8");
const manifest = JSON.parse(read("public/manifest.json")) as Record<
  string,
  unknown
> & {
  icons: Record<string, string>;
  action: { default_title: string; default_icon: Record<string, string> };
  side_panel: { default_path: string };
  permissions: string[];
  optional_host_permissions: string[];
  key: string;
  minimum_chrome_version: string;
};

const obs = () =>
  buildObservation({ doc: document, originKey: KEY, stateVersion: 1 });

describe("manifest", () => {
  it("declares the side panel, its page and the permission", () => {
    expect(manifest.permissions).toContain("sidePanel");
    expect(manifest.side_panel.default_path).toBe("sidepanel.html");
    expect(
      existsSync(join(ext, "public", manifest.side_panel.default_path)),
    ).toBe(true);
    expect(Number(manifest.minimum_chrome_version)).toBeGreaterThanOrEqual(114);
  });

  it("keeps the pinned key and asks for no new host access", () => {
    expect(manifest.key.length).toBeGreaterThan(300);
    expect(manifest.permissions.sort()).toEqual([
      "alarms",
      "scripting",
      "sidePanel",
      "storage",
      "webNavigation",
    ]);
    expect(manifest.optional_host_permissions).toEqual([
      "http://*/*",
      "https://*/*",
    ]);
    expect(manifest.host_permissions).toBeUndefined();
  });

  it("has icons at 16, 32, 48 and 128 px, for the extension and the toolbar action", () => {
    for (const size of ["16", "32", "48", "128"]) {
      for (const set of [manifest.icons, manifest.action.default_icon]) {
        const file = set[size];
        expect(file, `icon ${size}`).toBeTruthy();
        const png = readFileSync(join(ext, "public", file!));
        expect(png.subarray(1, 4).toString()).toBe("PNG");
        expect(png.readUInt32BE(16)).toBe(Number(size)); // IHDR width
        expect(png.readUInt32BE(20)).toBe(Number(size));
      }
    }
    expect(manifest.action.default_title).toContain("Wysp");
  });

  it("ships the options and side panel pages with the brand stylesheet", () => {
    for (const page of ["public/options.html", "public/sidepanel.html"]) {
      expect(read(page)).toContain("brand.css");
      expect(read(page)).toContain("icons/");
    }
    expect(read("public/brand.css")).toContain("#ca84fc");
  });
});

describe("panel target", () => {
  it("derives the Core's HTTP address from the adapter URL", () => {
    expect(coreHttpBase("ws://127.0.0.1:8765/ws/adapter")).toBe(
      "http://127.0.0.1:8765",
    );
    expect(coreHttpBase("wss://localhost:9000/ws/adapter")).toBe(
      "https://localhost:9000",
    );
    expect(coreHttpBase("ws://evil.example/ws/adapter")).toBeNull();
  });

  it("puts the token in the URL fragment, never in the path or query", () => {
    const t = panelTarget({
      coreUrl: DEFAULT_CONFIG.coreUrl,
      token: "abc-DEF_1.2",
    });
    expect(t).toEqual({
      kind: "ready",
      base: "http://127.0.0.1:8765",
      url: "http://127.0.0.1:8765/#wysp_token=abc-DEF_1.2&wysp_adapter=web-tutor",
    });
  });

  it("reports what is missing instead of guessing", () => {
    expect(
      panelTarget({ coreUrl: DEFAULT_CONFIG.coreUrl, token: "  " }).kind,
    ).toBe("no_token");
    expect(
      panelTarget({ coreUrl: DEFAULT_CONFIG.coreUrl, token: "a b&c" }).kind,
    ).toBe("bad_token");
    expect(
      panelTarget({ coreUrl: "ws://example.com/ws", token: "abc" }).kind,
    ).toBe("bad_url");
  });
});

describe("side panel fallback page", () => {
  const kinds = Object.keys(FALLBACKS) as FallbackKind[];

  it.each(kinds)(
    "%s: shows a branded message with a button to open the options page",
    (kind) => {
      document.body.innerHTML = `<div id="root"></div>`;
      const openSettings = vi.fn();
      const retry = vi.fn();
      renderFallback(document, document.getElementById("root")!, kind, {
        openSettings,
        retry,
      });
      expect(document.querySelector("h1")?.textContent).toBe(
        FALLBACKS[kind].title,
      );
      expect(document.querySelector("img")?.getAttribute("src")).toBe(
        "icons/icon-128.png",
      );
      expect(document.querySelectorAll("ol li").length).toBeGreaterThan(0);
      const settings = document.getElementById(
        "open-settings",
      ) as HTMLButtonElement;
      expect(settings.textContent).toBe("Open Wysp settings");
      settings.click();
      expect(openSettings).toHaveBeenCalledTimes(1);
      const retryBtn = document.getElementById(
        "retry",
      ) as HTMLButtonElement | null;
      expect(retryBtn !== null).toBe(kind === "unreachable");
      retryBtn?.click();
      expect(retry).toHaveBeenCalledTimes(kind === "unreachable" ? 1 : 0);
    },
  );

  it("tells the user how to start the Core when it is unreachable", () => {
    expect(FALLBACKS.unreachable.steps.join(" ")).toContain(
      "uv run wysp serve",
    );
    expect(FALLBACKS.no_token.steps.join(" ")).toContain("~/.wysp/token");
  });
});

describe("options status", () => {
  it("says connected or not connected and what to do", () => {
    expect(describeStatus("connected").tone).toBe("ok");
    for (const s of [
      "no_token",
      "bad_url",
      "refused",
      "disconnected",
      "stopped",
      undefined,
    ]) {
      const v = describeStatus(s, "boom");
      expect(v.tone).toBe("bad");
      expect(v.headline).toMatch(/^Not connected/);
      expect(v.advice.length).toBeGreaterThan(10);
    }
    expect(describeStatus("refused", "origin not allowed").advice).toContain(
      "origin not allowed",
    );
  });
});

describe("launcher", () => {
  const allowlist = () => ["http://localhost:5180"];
  const hostOf = () =>
    document.querySelector("[data-wysp-overlay]") as HTMLElement | null;
  const button = () =>
    hostOf()!.shadowRoot!.querySelector("button") as HTMLButtonElement;
  beforeEach(() => setPage(dashboardBody()));

  it("prop: WEB-P4 is not part of snapshots and leaves the page body untouched", () => {
    const before = stable(obs());
    const bodyBefore = document.body.innerHTML;
    const agent = new PageAgent(
      document,
      allowlist,
      () => undefined,
      async () => true,
      "open",
    );
    agent.start();
    expect(hostOf()).not.toBeNull();
    expect(stable(obs())).toEqual(before);
    expect(document.body.innerHTML).toBe(bodyBefore);
    expect(JSON.stringify(obs())).not.toContain(LAUNCHER_LABEL);
    agent.stop();
    expect(hostOf()).toBeNull();
    expect(stable(obs())).toEqual(before);
  });

  it("only appears on allowlisted origins, and not without an open-panel callback", () => {
    const off = new PageAgent(
      document,
      () => [],
      () => undefined,
      async () => true,
      "open",
    );
    off.start();
    expect(hostOf()).toBeNull();
    const none = new PageAgent(document, allowlist, () => undefined);
    none.start();
    expect(hostOf()).toBeNull();
    none.stop();
  });

  it("is a closed shadow root in the product", () => {
    const l = new Launcher(document, async () => true);
    l.show();
    expect(hostOf()!.shadowRoot).toBeNull(); // closed roots are invisible to the page
    l.hide();
  });

  it("opens the panel on a real click and ignores a click the page fabricated", async () => {
    const open = vi.fn(async () => true);
    const agent = new PageAgent(
      document,
      allowlist,
      () => undefined,
      open,
      "open",
    );
    agent.start();
    button().dispatchEvent(new MouseEvent("click", { bubbles: true })); // isTrusted is false
    expect(open).not.toHaveBeenCalled();
    button().dispatchEvent(trusted(new MouseEvent("click", { bubbles: true })));
    expect(open).toHaveBeenCalledTimes(1);
    expect(button().getAttribute("aria-label")).toBe(LAUNCHER_LABEL);
    agent.stop();
  });

  it("shows a tooltip when the browser refuses to open the panel", async () => {
    const agent = new PageAgent(
      document,
      allowlist,
      () => undefined,
      async () => false,
      "open",
    );
    agent.start();
    button().dispatchEvent(trusted(new MouseEvent("click", { bubbles: true })));
    await vi.waitFor(() => {
      const tip = hostOf()!.shadowRoot!.querySelector(".tip") as HTMLElement;
      expect(tip.hidden).toBe(false);
      expect(tip.textContent).toBe(LAUNCHER_FALLBACK_TEXT);
    });
    agent.stop();
  });

  it("a click on the launcher is not reported as something the user did on the page", () => {
    const sent: CsToSw[] = [];
    const agent = new PageAgent(
      document,
      allowlist,
      (m) => sent.push(m),
      async () => true,
      "open",
    );
    agent.start();
    button().dispatchEvent(
      trusted(new MouseEvent("click", { bubbles: true, composed: true })),
    );
    expect(sent.filter((m) => m.wyspEvent === "user_action")).toEqual([]);
    agent.stop();
  });
});

describe("brand", () => {
  const overlaySrc = read("src/cs/overlay.ts");
  const launcherSrc = read("src/cs/launcher.ts");

  it("overlay uses the lilac glow and a pink-accented label on surface, not the old teal", () => {
    expect(overlaySrc).toContain('GLOW = "#CA84FC"');
    expect(overlaySrc).toContain('LABEL_ACCENT = "#FE7C9C"');
    expect(overlaySrc).toContain("background: #1D0E4A");
    expect(overlaySrc).toContain("color: #F4E5FD");
    expect(overlaySrc).toContain("prefers-reduced-motion: no-preference");
    expect(overlaySrc.toLowerCase()).not.toContain("2dd4bf");
    expect(overlaySrc).not.toContain("45,212,191");
  });

  it("no extension file uses brand violet as a text colour or the old teal", () => {
    const files = [
      "public/brand.css",
      "public/options.html",
      "public/sidepanel.html",
      "src/cs/overlay.ts",
      "src/cs/launcher.ts",
    ];
    for (const f of files) {
      const text = read(f);
      expect(text.toLowerCase(), f).not.toContain("2dd4bf");
      expect(text, f).not.toMatch(/[^-]color:\s*(#6503fc|var\(--violet\))/i);
    }
    expect(launcherSrc).toContain("prefers-reduced-motion");
  });
});

// WCAG contrast of the dashboard palette pairs (text on its background must reach 4.5:1).
const lum = (hex: string): number => {
  const c = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
};
const ratio = (a: string, b: string): number => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

describe("demo dashboard look", () => {
  const css = readFileSync(
    join(here, "../../demo-dashboard/style.css"),
    "utf8",
  );
  const js = readFileSync(join(here, "../../demo-dashboard/app.js"), "utf8");

  it("uses the Wysp palette, not the Halloween teal", () => {
    for (const hex of [
      "#120532",
      "#1d0e4a",
      "#2a1766",
      "#f4e5fd",
      "#b9a3e3",
      "#ca84fc",
      "#fe7c9c",
      "#0d012f",
    ])
      expect(css).toContain(hex);
    expect(css.toLowerCase()).not.toContain("5eead4");
    expect(js.toLowerCase()).not.toContain("5eead4");
    expect(css).not.toMatch(/[^-]color:\s*(#6503fc|var\(--violet\))/i);
  });

  it("keeps every text/background pair at 4.5:1 or more", () => {
    const pairs: [string, string][] = [
      ["#f4e5fd", "#120532"],
      ["#f4e5fd", "#1d0e4a"],
      ["#f4e5fd", "#2a1766"],
      ["#b9a3e3", "#120532"],
      ["#b9a3e3", "#1d0e4a"],
      ["#ca84fc", "#120532"],
      ["#ca84fc", "#1d0e4a"],
      ["#0d012f", "#ca84fc"],
      ["#fe7c9c", "#1d0e4a"],
    ];
    for (const [fg, bg] of pairs)
      expect(ratio(fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps the accessible names the profile and fixtures rely on", () => {
    const html = readFileSync(
      join(here, "../../demo-dashboard/index.html"),
      "utf8",
    );
    for (const s of [
      "Haunted Shop Analytics",
      'id="region"',
      "Create report",
      "Reset demo",
      'aria-label="Orders table"',
    ])
      expect(html).toContain(s);
  });
});
