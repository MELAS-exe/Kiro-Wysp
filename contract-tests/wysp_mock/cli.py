"""`wysp-mock-adapter`: run the Kanban mock adapter and connect it to a running Core."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from wysp_adapter_sdk import AdapterClient

from .kanban import MockKanban, manifest


def default_token_path() -> Path:
    import os

    return Path(os.environ.get("WYSP_HOME") or Path.home() / ".wysp") / "token"


def start_mock(url: str, token: str) -> tuple[MockKanban, AdapterClient]:
    app = MockKanban()
    client = AdapterClient(manifest(), url, token, app.handle, state_version=app.state_version)
    app.client = client
    client.start()
    return app, client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wysp-mock-adapter")
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws/adapter")
    parser.add_argument("--token-file", type=Path, default=default_token_path())
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    token = args.token_file.read_text(encoding="utf-8").strip()
    app, client = start_mock(args.url, token)
    print(f"mock adapter connecting to {args.url} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        client.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
