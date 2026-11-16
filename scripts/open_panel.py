"""Open the Wysp Panel in a Chrome app window (no tabs, no address bar) at a given size and position.

    uv run --no-project python scripts/open_panel.py                      # side mode, docked right of the screen
    uv run --no-project python scripts/open_panel.py --mode compact       # 360 x 200, bottom right
    uv run --no-project python scripts/open_panel.py --mode full
    uv run --no-project python scripts/open_panel.py --width 480 --height 900 --x 1440 --y 0

The Panel remembers the last mode (`?mode=` in the URL wins). Use `--print` to see the command only.
Screen size is read from Windows (primary monitor, in physical pixels at the current scaling).
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys

PRESETS = {  # mode -> (width, height); None = use the screen
    "compact": (360, 200),
    "side": (480, None),
    "full": (None, None),
}


def screen_size() -> tuple[int, int]:
    if sys.platform != "win32":
        return 1920, 1080
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 - older Windows: sizes stay in scaled pixels
        pass
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def find_chrome() -> str | None:
    for name in ("chrome", "chrome.exe"):
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.exists(path):
                return path
    return None


def build_command(chrome: str, url: str, width: int, height: int, x: int, y: int) -> list[str]:
    return [chrome, f"--app={url}", f"--window-size={width},{height}", f"--window-position={x},{y}"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=sorted(PRESETS), default="side")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--url", default=None, help="override the Panel URL")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--x", type=int)
    ap.add_argument("--y", type=int)
    ap.add_argument("--print", action="store_true", help="print the command instead of running it")
    a = ap.parse_args()

    sw, sh = screen_size()
    pw, ph = PRESETS[a.mode]
    width = a.width or pw or sw
    height = a.height or ph or sh
    # Default placement: compact bottom right, side docked on the right edge, full at the origin.
    x = a.x if a.x is not None else (0 if a.mode == "full" else max(0, sw - width))
    y = a.y if a.y is not None else (max(0, sh - height - 48) if a.mode == "compact" else 0)
    url = a.url or f"http://127.0.0.1:{a.port}/?mode={a.mode}"

    chrome = find_chrome()
    if not chrome:
        print("Chrome not found: open this address in any browser window:", url, file=sys.stderr)
        return 1
    cmd = build_command(chrome, url, width, height, x, y)
    if a.print:
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        return 0
    subprocess.Popen(cmd)  # noqa: S603 - fixed argument list, no shell
    print(f"Panel: {url}  {width}x{height} at {x},{y}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
