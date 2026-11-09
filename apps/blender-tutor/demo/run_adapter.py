"""Run the Wysp adapter inside a headless Blender (no interface, manual pump loop).

    blender -b --python-use-system-env pumpkin.blend --python run_adapter.py -- --url ws://127.0.0.1:8765/ws/adapter --token-file ~/.wysp/token

Used by the Contract Test Kit and for scripted demos. With a window, install the extension instead.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ADAPTER_DIR = REPO / "apps" / "blender-tutor" / "adapter"


def load_adapter():
    """Import apps/blender-tutor/adapter as the package `wysp_tutor` (the name the extension has)."""
    sys.path.insert(0, str(REPO / "sdk" / "python"))  # editable installs (.pth) are not seen by Blender
    spec = importlib.util.spec_from_file_location(
        "wysp_tutor", ADAPTER_DIR / "__init__.py", submodule_search_locations=[str(ADAPTER_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["wysp_tutor"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws/adapter")
    parser.add_argument("--token")
    parser.add_argument("--token-file", type=Path, default=Path.home() / ".wysp" / "token")
    parser.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = run until killed)")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    token = args.token or args.token_file.read_text(encoding="utf-8").strip()

    pkg = load_adapter()
    from wysp_tutor.runtime import BlenderAdapter  # noqa: F401  (resolved through sys.modules)

    adapter = BlenderAdapter()
    adapter.watcher.fast_poll = True
    client = adapter.make_client(args.url, token)
    client.start()
    adapter.watcher.start()
    print("WYSP-ADAPTER-RUNNING", flush=True)
    deadline = time.monotonic() + args.seconds if args.seconds else None
    try:
        while deadline is None or time.monotonic() < deadline:
            adapter.tick()
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        adapter.shutdown()
    del pkg
    return 0


if __name__ == "__main__":
    sys.exit(main())
