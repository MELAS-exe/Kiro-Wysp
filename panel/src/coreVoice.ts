// Voice through the Core, for Panels whose browser cannot listen or speak (the IDE's embedded browser).
//   Listening: the Core records the default microphone only between start and stop, then transcribes the clip
//   (POST /api/listen/*). That endpoint needs the pairing token: a host that embeds this Panel passes it once in the
//   URL fragment (#wysp_token=...). The fragment never reaches a server, and it is removed from the address at once.
//   Speaking: the Core synthesises with the voices installed on the machine (POST /api/tts, no token needed).

import { t } from "./i18n";

let token: string | null = null;
/** The application the host wants the tutor to look at (#wysp_adapter=web-tutor): a browser side panel asks for itself. */
export let preferredAdapter: string | null = null;

(function captureToken(): void {
  if (typeof location === "undefined") return; // unit tests run without a browser
  preferredAdapter = /[#&]wysp_adapter=([\w.-]+)/.exec(location.hash)?.[1] ?? null;
  const m = /[#&]wysp_token=([\w.-]+)/.exec(location.hash);
  if (!m) return;
  token = m[1] ?? null;
  history.replaceState(null, "", location.pathname + location.search);
})();

/** True when the host gave this Panel the token, so the Core can do the listening. */
export const hasCoreListen = (): boolean => token !== null;

async function post(path: string, init: RequestInit & { headers?: Record<string, string> } = {}): Promise<Response> {
  return fetch(path, { method: "POST", ...init, headers: { ...(init.headers ?? {}), ...(token ? { "X-Wysp-Token": token } : {}) } });
}

async function errorText(r: Response, fallback: string): Promise<string> {
  try {
    const j = (await r.json()) as { error?: string };
    return j.error ?? fallback;
  } catch {
    return fallback;
  }
}

/** Start recording. Returns an error message, or null when the Core is listening. */
export async function coreListenStart(): Promise<string | null> {
  try {
    const r = await post("/api/listen/start", { body: "{}", headers: { "Content-Type": "application/json" } });
    return r.ok ? null : t("voice.micError", { error: await errorText(r, t("voice.httpError", { status: r.status })) });
  } catch {
    return t("voice.micUnreachable");
  }
}

/** Stop recording and transcribe. */
export async function coreListenStop(): Promise<{ text: string } | { error: string }> {
  try {
    const r = await post("/api/listen/stop", { body: "{}", headers: { "Content-Type": "application/json" } });
    if (!r.ok) return { error: t("voice.sttError", { error: await errorText(r, t("voice.httpError", { status: r.status })) }) };
    const j = (await r.json()) as { text?: string };
    return { text: (j.text ?? "").trim() };
  } catch {
    return { error: t("voice.sttUnreachable") };
  }
}

export function coreListenCancel(): void {
  void post("/api/listen/cancel", { body: "{}", headers: { "Content-Type": "application/json" } }).catch(() => undefined);
}

let neural: Promise<boolean> | null = null;
/** True when the Core speaks with a neural voice, which sounds better than the browser's: it is then preferred. */
export function coreHasNeuralVoice(): Promise<boolean> {
  neural ??= fetch("/api/health")
    .then((r) => r.json())
    .then((j: { tts?: string | null }) => j.tts === "kokoro")
    .catch(() => false);
  return neural;
}

/** Audio of `text` in the Core's local voice, or null when the Core has none (the caption then stands alone). */
export async function coreSpeak(text: string, lang: string): Promise<Blob | null> {
  try {
    const r = await post("/api/tts", { body: JSON.stringify({ text, lang }), headers: { "Content-Type": "application/json" } });
    return r.ok ? await r.blob() : null;
  } catch {
    return null;
  }
}
