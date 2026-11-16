"""`wysp` command line."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .app import Config, create_app, find_repo_root
from .llm import ExternalLLM, LLMError, ScriptedLLM, from_env
from .store import ensure_home, load_or_create_token, wysp_home


def _mcp_config(port: int) -> int:
    """Print client setup for the /mcp endpoint. The pairing token itself is never printed."""
    ensure_home()
    load_or_create_token()
    url = f"http://127.0.0.1:{port}/mcp"
    token_file = wysp_home() / "token"
    print(
        f"""Wysp MCP endpoint: {url}
Start the Core without its own model:   uv run wysp serve --llm external

The endpoint needs the pairing token on every request. Put it in an environment variable
(the token is not printed here; it lives in {token_file}):

  PowerShell:  $env:WYSP_TOKEN = (Get-Content "{token_file}" -Raw).Trim()
  bash/zsh:    export WYSP_TOKEN="$(cat '{token_file}')"

Then register the endpoint with your MCP client, for example:

  Claude Code:  claude mcp add --transport http wysp {url} --header "Authorization: Bearer $WYSP_TOKEN"
  kiro-cli:     add to .kiro/settings/mcp.json (or ~/.kiro/settings/mcp.json):
                {{"mcpServers": {{"wysp": {{"url": "{url}",
                  "headers": {{"Authorization": "Bearer ${{WYSP_TOKEN}}"}}}}}}}}
  Other clients: streamable HTTP, URL above, header  Authorization: Bearer <token>

Open the Panel (http://127.0.0.1:{port}) next to your agent, ask it to use the Wysp tools
(it starts with get_tutor_context), or type in the Panel and ask it to run the Wysp loop (wait_for_user)."""
    )
    return 0


def _logs(args: argparse.Namespace) -> int:
    import json

    from .telemetry import analyze

    files = analyze.list_logs()
    if args.action == "list":
        for p in files:
            print(f"{p.stat().st_size:>9}  {p}")
        return 0
    core = [p for p in files if p.name.startswith("core-")]
    target = args.file or (core[0] if core else None)
    if args.action == "path":
        print(analyze.log_dir())
        return 0
    if target is None or not Path(target).exists():
        print("No core log found. Run a session first (telemetry is on by default).", file=sys.stderr)
        return 1
    if args.action == "timeline":
        print(analyze.timeline(Path(target)))
        return 0
    summary = analyze.summarize(Path(target))
    print(json.dumps(summary, indent=2, default=str) if args.json else analyze.render(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wysp", description="Wysp: AI tutors for software applications")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the Core and serve the Panel")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument(
        "--llm",
        default="auto",
        help="auto | scripted | external | groq | openrouter | cerebras | pollinations | openai | ollama "
        "(external: no model in the Core, an AI agent connects through /mcp)",
    )
    serve.add_argument("--mcp", action="store_true", help="also serve /mcp when the Core has its own LLM")
    serve.add_argument("--scenario", help="scenario YAML for --llm scripted")
    serve.add_argument("--lang", default="en")
    serve.add_argument(
        "--no-survey",
        action="store_true",
        help="do not survey the application when it becomes active (WYSP_SURVEY=off)",
    )
    serve.add_argument("--unsafe-bind", action="store_true", help="allow a non-loopback host (NOT recommended)")
    serve.add_argument("--log-level", default="info", help="console verbosity")
    serve.add_argument(
        "--log", choices=("off", "basic", "full"), help="session telemetry level (default: WYSP_LOG or full)"
    )

    logs = sub.add_parser("logs", help="inspect session telemetry written to ~/.wysp/logs")
    logs.add_argument("action", choices=("list", "summary", "timeline", "path"))
    logs.add_argument("--file", type=Path, help="a log file (default: the newest core log)")
    logs.add_argument("--json", action="store_true", help="machine-readable summary")

    sub.add_parser("token", help="print the location of the pairing token")

    mcp_cfg = sub.add_parser("mcp-config", help="show how to connect an AI agent (MCP client) to a running Core")
    mcp_cfg.add_argument("--port", type=int, default=8765)

    sub.add_parser("install-voice", help="download the offline female voice model (about 115 MB, once)")

    validate = sub.add_parser("validate-profile", help="check a tutor profile directory")
    validate.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    load_dotenv(find_repo_root() / ".env")

    if args.command == "validate-profile":
        from .pedagogy.profile import validate_profile

        problems = validate_profile(args.path)
        for p in problems:
            print(f"ERROR {p}", file=sys.stderr)
        return 1 if problems else 0

    if args.command == "install-voice":
        from .tts import KOKORO_DIR, install_kokoro, kokoro_ready

        install_kokoro()
        print(f"Voice model in {KOKORO_DIR}")
        if not kokoro_ready():
            print(
                "Also run: uv sync --package wysp-core --extra voice  (installs kokoro-onnx and soundfile)",
                file=sys.stderr,
            )
            return 1
        return 0

    if args.command == "logs":
        return _logs(args)

    if args.command == "mcp-config":
        return _mcp_config(args.port)

    if args.command == "token":
        ensure_home()
        load_or_create_token()
        print(wysp_home() / "token")
        return 0

    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.unsafe_bind:
        print(
            "Refusing to bind a non-loopback address. Wysp is local-only; pass --unsafe-bind to override.",
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        if args.llm == "scripted":
            if not args.scenario:
                print("--llm scripted needs --scenario FILE", file=sys.stderr)
                return 2
            llm = ScriptedLLM.from_file(args.scenario)
        elif args.llm == "external":
            llm = ExternalLLM()
        else:
            if args.llm != "auto":
                os.environ["WYSP_LLM_PROVIDER"] = args.llm
            llm = from_env()
    except LLMError as exc:
        print(f"LLM setup failed: {exc}", file=sys.stderr)
        return 2

    import uvicorn

    config = Config(host=args.host, port=args.port, lang=args.lang, log_level=args.log, mcp=args.mcp)
    if args.no_survey:
        config.survey = False
    app = create_app(config, llm)
    print(
        f"Wysp Core on http://{args.host}:{args.port}  (LLM: {llm.name}, pairing token: {Path(wysp_home() / 'token')})"
    )
    if getattr(app.state, "mcp", None) is not None:
        print(f"MCP endpoint: http://{args.host}:{args.port}/mcp  (run `wysp mcp-config` for client setup)")
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
