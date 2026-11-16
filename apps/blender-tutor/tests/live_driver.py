"""Headless Blender for the pedagogy live test: the real adapter plus a scripted "user".

    blender -b --python-use-system-env pumpkin.blend --python live_driver.py -- --url ws://... --token T --commands cmd.json

The adapter runs exactly as in demo/run_adapter.py. The test writes a JSON command file; this driver
performs it with plain `bpy` data-API calls, the way a click in the interface would change the scene
(nobody tells the adapter that a user did it, so the origin tag comes from the adapter's own detection).
The command set is closed (no code is ever evaluated), and it exists for tests only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import bpy  # noqa: E402
import run_adapter  # noqa: E402


def _select(name: str) -> None:
    for o in bpy.context.view_layer.objects:
        o.select_set(o.name == name)
    bpy.context.view_layer.objects.active = bpy.data.objects[name]


def _move_modifier(obj: str, modifier: str, index: int) -> None:
    bpy.data.objects[obj].modifiers.move([m.name for m in bpy.data.objects[obj].modifiers].index(modifier), index)


def _add_modifier(obj: str, kind: str, name: str) -> None:
    bpy.data.objects[obj].modifiers.new(name, kind)


def _set_modifier_property(obj: str, modifier: str, prop: str, value) -> None:
    setattr(bpy.data.objects[obj].modifiers[modifier], prop, value)


COMMANDS = {
    "select": _select,
    "move_modifier": _move_modifier,
    "add_modifier": _add_modifier,
    "set_modifier_property": _set_modifier_property,
}


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--commands", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=120)
    args = parser.parse_args(argv)

    run_adapter.load_adapter()
    from wysp_tutor.runtime import BlenderAdapter

    adapter = BlenderAdapter()
    adapter.watcher.fast_poll = True
    client = adapter.make_client(args.url, args.token)
    client.start()
    adapter.watcher.start()
    print("WYSP-DRIVER-RUNNING", flush=True)
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            adapter.tick()
            if args.commands.exists():
                try:
                    spec = json.loads(args.commands.read_text(encoding="utf-8"))
                except ValueError:
                    spec = None  # half-written file: read it on the next turn
                if spec is not None:
                    args.commands.unlink()
                    COMMANDS[spec["name"]](*spec.get("args", []))
                    print("WYSP-DRIVER-DID", spec["name"], flush=True)
            time.sleep(0.01)
    finally:
        adapter.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
