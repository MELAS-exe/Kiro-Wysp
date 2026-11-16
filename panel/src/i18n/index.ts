// Tiny dependency-free i18n. Strings live in en.json and fr.json (same keys). Language order: the Core's
// session.state `lang` when it is "fr" or "en", else `?lang=`, else navigator.language, else English.
import { useSyncExternalStore } from "react";
import en from "./en.json";
import fr from "./fr.json";

export type Lang = "en" | "fr";
export type Dict = Record<string, string>;
export const DICTS: Record<Lang, Dict> = { en, fr };

const asLang = (v: string | null | undefined): Lang | null => {
  const base = (v ?? "").toLowerCase().slice(0, 2);
  return base === "fr" || base === "en" ? base : null;
};

/** Language from `?lang=` or the browser, English by default. */
export function detectLang(): Lang {
  const fromUrl =
    typeof location !== "undefined"
      ? asLang(new URLSearchParams(location.search).get("lang"))
      : null;
  const fromBrowser =
    typeof navigator !== "undefined" ? asLang(navigator.language) : null;
  return fromUrl ?? fromBrowser ?? "en";
}

let detected: Lang = detectLang();
let session: Lang | null = null;
const listeners = new Set<() => void>();

export const getLang = (): Lang => session ?? detected;

function emit(): void {
  listeners.forEach((l) => l());
}

/** The Core's session language: used when it is fr or en, ignored otherwise. */
export function setSessionLang(lang: string | null | undefined): void {
  const next = asLang(lang);
  if (next === session) return;
  session = next;
  emit();
}

/** Forces the language and clears the session one (tests, and a `?lang=` change). */
export function setLang(lang: Lang | null): void {
  session = null;
  detected = lang ?? detectLang();
  emit();
}

export type Params = Record<string, string | number>;

/** Translate `key` (falls back to English, then to the key itself) and fill `{name}` placeholders from `params`. */
export function t(key: string, params?: Params): string {
  const raw = DICTS[getLang()][key] ?? DICTS.en[key] ?? key;
  if (!params) return raw;
  return raw.replace(/\{(\w+)\}/g, (m, name: string) =>
    name in params ? String(params[name]) : m,
  );
}

/** `t` for components: re-renders them when the language changes. */
export function useT(): typeof t {
  useSyncExternalStore(
    (cb) => (listeners.add(cb), () => void listeners.delete(cb)),
    getLang,
  );
  return t;
}
