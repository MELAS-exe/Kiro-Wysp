"""Build (and optionally install) the Wysp Tutor Blender extension.

    uv run python scripts/build_blender_extension.py            # build dist/wysp_tutor-<version>.zip
    uv run python scripts/build_blender_extension.py --install  # also install + enable it in your Blender

Steps: build the SDK wheel, fetch the pure-Python websocket-client wheel, then run Blender's own
`extension build`, which validates blender_manifest.toml. Needs internet only for the wheel download.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "apps" / "blender-tutor" / "adapter"
WHEELS = ADAPTER / "wheels"
DIST = REPO / "dist"
WEBSOCKET_CLIENT = "websocket-client==1.9.2"


def blender_exe() -> Path:
    exe = Path(os.environ.get("WYSP_BLENDER", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))
    if not exe.exists():
        sys.exit(f"Blender not found at {exe}. Set WYSP_BLENDER.")
    return exe


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=True, text=True, **kw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="install and enable the built extension in Blender")
    args = parser.parse_args()

    manifest = tomllib.loads((ADAPTER / "blender_manifest.toml").read_text(encoding="utf-8"))
    wheels_expected = [Path(w).name for w in manifest.get("wheels", [])]

    shutil.rmtree(WHEELS, ignore_errors=True)
    WHEELS.mkdir(parents=True)
    uv = shutil.which("uv") or "uv"
    run([uv, "build", "--wheel", str(REPO / "sdk" / "python"), "--out-dir", str(WHEELS)])
    run([uv, "run", "--no-project", "--with", "pip", "python", "-m", "pip", "download", WEBSOCKET_CLIENT,
         "--no-deps", "--only-binary=:all:", "-d", str(WHEELS), "--quiet"])  # fmt: skip
    present = sorted(p.name for p in WHEELS.glob("*.whl"))
    missing = [w for w in wheels_expected if w not in present]
    if missing:
        sys.exit(f"manifest lists wheels that were not produced: {missing}; present: {present}")

    DIST.mkdir(exist_ok=True)
    for old in DIST.glob("wysp_tutor-*.zip"):
        old.unlink()
    blender = str(blender_exe())
    run([blender, "--command", "extension", "build", "--source-dir", str(ADAPTER), "--output-dir", str(DIST)])
    built = sorted(DIST.glob("wysp_tutor-*.zip"))
    if not built:
        sys.exit("no extension zip was produced")
    print(f"\nbuilt: {built[-1]}")
    if args.install:
        run([blender, "--command", "extension", "install-file", "-r", "user_default", "-e", str(built[-1])])
        print("installed and enabled. Open Blender: 3D Viewport sidebar (N) > Wysp tab > Connect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
