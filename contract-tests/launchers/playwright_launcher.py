"""Online contract run for the web tutor (fixture `launch.kind: playwright`).

    uv run --no-sync wysp-contract --tutor web-tutor [--junit out.xml]

This script is a shortcut for the same thing. The launcher itself is `wysp_contract.launch` (it starts the Node
driver `apps/web-tutor/extension/tests/live/playwright_driver.mjs`, which loads the built extension in Chromium and
serves a copy of the demo dashboard on a free port, never 5180), and the harness is `wysp_contract.harness` (a
throw-away server on a free port with its own pairing token; the Core and `~/.wysp` are not involved).

Needs `npm.cmd run build -w apps/web-tutor/extension` first. Exit code 0 means all green.
"""

from __future__ import annotations

import argparse
import sys

from wysp_contract.cli import main as kit


def main() -> int:
    parser = argparse.ArgumentParser(prog="playwright_launcher")
    parser.add_argument("--tutor", default="web-tutor")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--junit")
    args = parser.parse_args()
    argv = ["--tutor", args.tutor, "--timeout", str(args.timeout)]
    if args.junit:
        argv += ["--junit", args.junit]
    return kit(argv)


if __name__ == "__main__":
    sys.exit(main())
