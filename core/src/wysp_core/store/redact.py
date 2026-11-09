"""Secret redaction for logs, audit records and anything sent to an LLM."""

from __future__ import annotations

import os
import re
from typing import Any

_SECRET_ENV = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)
_registered: set[str] = set()


def register_secret(value: str | None) -> None:
    if value and len(value) >= 8:
        _registered.add(value)


def register_env_secrets() -> None:
    for name, value in os.environ.items():
        if name.startswith(("WYSP_", "GROQ_", "OPENROUTER_", "CEREBRAS_", "GEMINI_", "GOOGLE_")) and _SECRET_ENV.search(
            name
        ):
            register_secret(value)


def redact_text(text: str) -> str:
    for secret in sorted(_registered, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    return text


def redact(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def clear_registered() -> None:  # for tests
    _registered.clear()
