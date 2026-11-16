/** Extension settings (chrome.storage.local) and the origin allowlist rules shared by every part. */

export interface WebConfig {
  /** ws://127.0.0.1:8765/ws/adapter. Only loopback addresses are accepted. */
  coreUrl: string;
  /** Pairing token (contents of ~/.wysp/token). Never logged, never sent anywhere except the Core hello. */
  token: string;
  /** Allowlisted origins, e.g. http://localhost:5180. Empty means the extension reads nothing. */
  allowlist: string[];
}

export const DEFAULT_ORIGIN = "http://localhost:5180";

export const DEFAULT_CONFIG: WebConfig = {
  coreUrl: "ws://127.0.0.1:8765/ws/adapter",
  token: "",
  allowlist: [DEFAULT_ORIGIN],
};

/** Returns the canonical origin (scheme://host[:port]) of an http(s) URL, or null. */
export function normalizeOrigin(input: string): string | null {
  try {
    const url = new URL(input.trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

/** True when `origin` is exactly one of the allowlisted origins (no wildcards, no subdomain matching). */
export function originAllowed(
  origin: string | null | undefined,
  allowlist: readonly string[],
): boolean {
  if (!origin) return false;
  const normalized = normalizeOrigin(origin);
  if (!normalized) return false;
  return allowlist.some((entry) => normalizeOrigin(entry) === normalized);
}

/** The Core must be on this machine: only loopback hosts are accepted. */
export function isLoopbackCoreUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "ws:" || url.protocol === "wss:") &&
      ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    );
  } catch {
    return false;
  }
}

/** Chrome match pattern for the content script and the optional host permission of an origin. */
export function matchPattern(origin: string): string {
  return `${origin}/*`;
}

/** `localhost:5180` for http://localhost:5180 (used in refs: web://<originKey>/...). */
export function originKey(origin: string): string {
  return new URL(origin).host;
}

/** `http://127.0.0.1:8765` for ws://127.0.0.1:8765/ws/adapter (the Core serves the Panel on the same host and port). */
export function coreHttpBase(coreUrl: string): string | null {
  if (!isLoopbackCoreUrl(coreUrl)) return null;
  const url = new URL(coreUrl);
  return `${url.protocol === "wss:" ? "https:" : "http:"}//${url.host}`;
}

export type PanelTarget =
  | { kind: "ready"; base: string; url: string }
  | { kind: "no_token" }
  | { kind: "bad_token" }
  | { kind: "bad_url" };

/** What the side panel should open. The pairing token travels in the URL fragment, which never reaches a server. */
export function panelTarget(config: Pick<WebConfig, "coreUrl" | "token">): PanelTarget {
  const base = coreHttpBase(config.coreUrl);
  if (!base) return { kind: "bad_url" };
  const token = config.token.trim();
  if (!token) return { kind: "no_token" };
  if (!/^[\w.-]+$/.test(token)) return { kind: "bad_token" };
  return { kind: "ready", base, url: `${base}/#wysp_token=${token}&wysp_adapter=web-tutor` };
}
