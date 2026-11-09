"""`wysp` command line."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .app import Config, create_app, find_repo_root
from .llm import LLMError, ScriptedLLM, from_env
from .store import ensure_home, load_or_create_token, wysp_home


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wysp", description="Wysp: AI tutors for software applications")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the Core and serve the Panel")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument(
        "--llm", default="auto", help="auto | scripted | groq | openrouter | cerebras | pollinations | openai | ollama"
    )
    serve.add_argument("--scenario", help="scenario YAML for --llm scripted")
    serve.add_argument("--lang", default="en")
    serve.add_argument("--unsafe-bind", action="store_true", help="allow a non-loopback host (NOT recommended)")
    serve.add_argument("--log-level", default="info")

    sub.add_parser("token", help="print the location of the pairing token")

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
        else:
            if args.llm != "auto":
                os.environ["WYSP_LLM_PROVIDER"] = args.llm
            llm = from_env()
    except LLMError as exc:
        print(f"LLM setup failed: {exc}", file=sys.stderr)
        return 2

    import uvicorn

    config = Config(host=args.host, port=args.port, lang=args.lang)
    app = create_app(config, llm)
    print(
        f"Wysp Core on http://{args.host}:{args.port}  (LLM: {llm.name}, pairing token: {Path(wysp_home() / 'token')})"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
