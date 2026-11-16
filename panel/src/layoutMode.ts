// Layout modes (requirement 1.4): compact (about 360 x 200), side (default), full. The last choice is remembered;
// `?mode=compact` in the URL wins (used by scripts/open_panel.py and docs/demo-setup.md).
export type LayoutMode = "compact" | "side" | "full";
export const LAYOUT_MODES: readonly LayoutMode[] = ["compact", "side", "full"];
const KEY = "wysp.mode";

export function parseMode(v: unknown): LayoutMode | null {
  return LAYOUT_MODES.find((m) => m === v) ?? null;
}

export function initialMode(search: string, stored: string | null): LayoutMode {
  return (
    parseMode(new URLSearchParams(search).get("mode")) ??
    parseMode(stored) ??
    "side"
  );
}

export function loadMode(): LayoutMode {
  try {
    return initialMode(
      window.location.search,
      window.localStorage.getItem(KEY),
    );
  } catch {
    return "side";
  }
}

/** Applies the mode to the page (CSS reads `html[data-mode]`) and remembers it. */
export function applyMode(mode: LayoutMode): void {
  document.documentElement.dataset.mode = mode;
  try {
    window.localStorage.setItem(KEY, mode);
  } catch {
    /* private mode: not remembered */
  }
}
