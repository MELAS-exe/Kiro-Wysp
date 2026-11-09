"""OpenAI-compatible chat provider (Groq, OpenRouter, Cerebras, Pollinations, OpenAI, Ollama...).

Non-streaming for robustness with free endpoints. Secrets never leave this module except in the
Authorization header, and every error message is redacted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from ..store import redact_text, register_secret
from .base import CancelToken, LLMError, LLMResult, ToolCall, ToolSpec

log = logging.getLogger("wysp.llm")


@dataclass(frozen=True)
class Preset:
    base_url: str
    model: str
    key_env: tuple[str, ...]
    needs_key: bool = True


# Free tiers, no credit card (checked 9 Nov 2026). Models change often: override with WYSP_LLM_MODEL.
PRESETS: dict[str, Preset] = {
    "groq": Preset("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", ("GROQ_API_KEY",)),
    "openrouter": Preset(
        "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free", ("OPENROUTER_API_KEY",)
    ),
    "cerebras": Preset("https://api.cerebras.ai/v1", "gpt-oss-120b", ("CEREBRAS_API_KEY",)),
    "pollinations": Preset("https://text.pollinations.ai/openai", "openai", (), needs_key=False),
    "openai": Preset("https://api.openai.com/v1", "gpt-4o-mini", ("OPENAI_API_KEY",)),
    "ollama": Preset("http://127.0.0.1:11434/v1", "llama3.1", (), needs_key=False),
}


class OpenAICompatProvider:
    def __init__(
        self, name: str, base_url: str, model: str, api_key: str | None = None, timeout_s: float = 45.0
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self._key = api_key
        register_secret(api_key)

    @property
    def endpoint(self) -> str:
        return self.base_url if self.base_url.endswith("/chat/completions") else self.base_url + "/chat/completions"

    async def complete(self, messages: list[dict[str, Any]], tools: list[ToolSpec], cancel: CancelToken) -> LLMResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._clean(messages),
            "temperature": 0.3,
            "max_tokens": 1200,
        }
        if tools:
            body["tools"] = [t.to_openai() for t in tools]
            body["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"

        async def post() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                return await client.post(self.endpoint, headers=headers, json=body)

        task = asyncio.create_task(post())
        waiter = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if task not in done:
                task.cancel()
                return LLMResult()
            response = task.result()
        except httpx.HTTPError as exc:
            raise LLMError(redact_text(f"{self.name}: network error ({type(exc).__name__})")) from exc
        finally:
            waiter.cancel()
        if response.status_code >= 400:
            snippet = redact_text(response.text[:200].replace("\n", " "))
            raise LLMError(f"{self.name}: HTTP {response.status_code} {snippet}")
        return self._parse(response)

    @staticmethod
    def _clean(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Some providers reject the non-standard `name` field on tool messages."""
        return [{k: v for k, v in m.items() if not (m.get("role") == "tool" and k == "name")} for m in messages]

    def _parse(self, response: httpx.Response) -> LLMResult:
        try:
            message = response.json()["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"{self.name}: unexpected response format") from exc
        calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (json.JSONDecodeError, TypeError, ValueError):
                args = {"_unparsed": str(raw_args)[:300]}
            calls.append(ToolCall(id=tc.get("id") or uuid.uuid4().hex[:8], name=fn.get("name", ""), arguments=args))
        return LLMResult(text=(message.get("content") or "").strip(), tool_calls=calls)


def from_env(env: dict[str, str] | None = None) -> OpenAICompatProvider:
    """Pick a provider from environment variables.

    WYSP_LLM_PROVIDER: groq | openrouter | cerebras | pollinations | openai | ollama | custom
    WYSP_LLM_MODEL, WYSP_LLM_BASE_URL, WYSP_LLM_API_KEY override the preset.
    Without WYSP_LLM_PROVIDER: the first provider whose key is present, else keyless Pollinations.
    """
    env = dict(os.environ) if env is None else env
    name = (env.get("WYSP_LLM_PROVIDER") or "").lower()
    if not name:
        for candidate in ("groq", "openrouter", "cerebras"):
            if any(env.get(k) for k in PRESETS[candidate].key_env):
                name = candidate
                break
        else:
            name = "pollinations"
    preset = PRESETS.get(name)
    if preset is None:
        base_url = env.get("WYSP_LLM_BASE_URL")
        if not base_url:
            raise LLMError(f"unknown provider '{name}': set WYSP_LLM_BASE_URL or pick one of {sorted(PRESETS)}")
        preset = Preset(base_url, env.get("WYSP_LLM_MODEL", "default"), (), needs_key=False)
    key = env.get("WYSP_LLM_API_KEY") or next((env[k] for k in preset.key_env if env.get(k)), None)
    if preset.needs_key and not key:
        raise LLMError(
            f"provider '{name}' needs an API key: set {preset.key_env[0] if preset.key_env else 'WYSP_LLM_API_KEY'}"
        )
    return OpenAICompatProvider(
        name=name,
        base_url=env.get("WYSP_LLM_BASE_URL") or preset.base_url,
        model=env.get("WYSP_LLM_MODEL") or preset.model,
        api_key=key,
    )
