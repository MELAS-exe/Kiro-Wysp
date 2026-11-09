"""OpenAI-compatible chat provider (Groq, OpenRouter, Cerebras, Pollinations, OpenAI, Ollama...).

Non-streaming for robustness with free endpoints. Secrets never leave this module except in the
Authorization header, and every error message is redacted.

Free endpoints are unreliable, so requests are resilient:
* HTTP 429 honours `Retry-After` (capped) and tries again;
* 5xx and timeouts are retried;
* `hedge_after_s`: when set, a second identical request is launched if nothing came back in that
  time (LLM calls have no side effects), and the first successful answer wins. Pollinations'
  anonymous tier stalls on roughly every other request, so it is enabled for that preset.

Every call is measured (telemetry kind `llm.request`): attempts, stalls, rate limits and the waiting they
caused, token usage reported by the API, prompt and reply sizes, and the final outcome.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from ..store import redact_text, register_secret
from .base import CancelToken, LLMError, LLMResult, ToolCall, ToolSpec

log = logging.getLogger("wysp.llm")

MAX_RETRY_AFTER_S = 20.0


@dataclass(frozen=True)
class Preset:
    base_url: str
    model: str
    key_env: tuple[str, ...]
    needs_key: bool = True
    hedge_after_s: float | None = None
    timeout_s: float = 45.0
    max_attempts: int = 3


# Free tiers, no credit card (checked 9 Nov 2026). Models change often: override with WYSP_LLM_MODEL.
PRESETS: dict[str, Preset] = {
    "groq": Preset("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", ("GROQ_API_KEY",)),
    "openrouter": Preset(
        "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free", ("OPENROUTER_API_KEY",)
    ),
    "cerebras": Preset("https://api.cerebras.ai/v1", "gpt-oss-120b", ("CEREBRAS_API_KEY",)),
    "pollinations": Preset(
        "https://text.pollinations.ai/openai",
        "openai",
        (),
        needs_key=False,
        hedge_after_s=9.0,
        timeout_s=30.0,
        max_attempts=5,
    ),
    "openai": Preset("https://api.openai.com/v1", "gpt-4o-mini", ("OPENAI_API_KEY",)),
    "ollama": Preset("http://127.0.0.1:11434/v1", "llama3.1", (), needs_key=False, timeout_s=120.0),
}


class OpenAICompatProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 45.0,
        hedge_after_s: float | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.hedge_after_s = hedge_after_s
        self.max_attempts = max_attempts
        self.telemetry = None  # set by the app; a wysp_core.telemetry.Telemetry
        self._key = api_key
        register_secret(api_key)

    @property
    def endpoint(self) -> str:
        return self.base_url if self.base_url.endswith("/chat/completions") else self.base_url + "/chat/completions"

    async def _post(self, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            return await client.post(self.endpoint, headers=headers, json=body)

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

        stats: dict[str, Any] = {
            "attempts": 0,
            "timeouts": 0,
            "network_errors": 0,
            "rate_limited": 0,
            "rate_wait_ms": 0.0,
            "server_errors": 0,
            "statuses": [],
        }
        started = time.monotonic()
        result: LLMResult | None = None
        usage: dict[str, Any] | None = None
        error: str | None = None
        cancelled = False
        try:
            response = await self._run(body, headers, cancel, stats)
            if response is None:
                cancelled = True
                return LLMResult()
            if isinstance(response, LLMResult):
                result = response  # recovered from a rejected generation
                return result
            result = self._parse(response)
            usage = _usage(response)
            return result
        except LLMError as exc:
            error = str(exc)
            raise
        finally:
            self._record(messages, tools, started, stats, result, usage, error, cancelled)

    async def _run(self, body, headers, cancel: CancelToken, stats: dict[str, Any]):
        waiter = asyncio.create_task(cancel.wait())
        running: set[asyncio.Task] = set()
        launched = 0
        last_problem = "no answer"
        try:
            while True:
                if launched < self.max_attempts and (not running or self.hedge_after_s is not None):
                    running.add(asyncio.create_task(self._post(body, headers)))
                    launched += 1
                    stats["attempts"] = launched
                if not running:
                    raise LLMError(f"{self.name}: {last_problem}")
                done, _ = await asyncio.wait(
                    {waiter, *running}, timeout=self.hedge_after_s, return_when=asyncio.FIRST_COMPLETED
                )
                if waiter in done:
                    return None
                for task in done:
                    running.discard(task)
                    try:
                        response = task.result()
                    except httpx.TimeoutException as exc:
                        stats["timeouts"] += 1
                        last_problem = f"network error ({type(exc).__name__})"
                        log.warning("%s: %s", self.name, last_problem)
                        continue
                    except httpx.HTTPError as exc:
                        stats["network_errors"] += 1
                        last_problem = f"network error ({type(exc).__name__})"
                        log.warning("%s: %s", self.name, last_problem)
                        continue
                    stats["statuses"].append(response.status_code)
                    if response.status_code == 429:
                        pause = min(self._retry_after(response), MAX_RETRY_AFTER_S)
                        stats["rate_limited"] += 1
                        stats["rate_wait_ms"] += pause * 1000
                        last_problem = f"rate limited (retry after {pause:.0f}s)"
                        log.warning("%s: %s", self.name, last_problem)
                        if launched >= self.max_attempts and not running:
                            raise LLMError(f"{self.name}: {last_problem}")
                        await asyncio.sleep(pause)
                        continue
                    if response.status_code >= 500:
                        stats["server_errors"] += 1
                        last_problem = f"server error HTTP {response.status_code}"
                        log.warning("%s: %s", self.name, last_problem)
                        continue
                    if response.status_code >= 400:
                        recovered = self._recover_failed_generation(response)
                        if recovered is not None:
                            log.info("%s: recovered a tool call from a rejected generation", self.name)
                            stats["recovered_generation"] = True
                            return recovered
                        snippet = redact_text(response.text[:200].replace("\n", " "))
                        raise LLMError(f"{self.name}: HTTP {response.status_code} {snippet}")
                    return response
        finally:
            waiter.cancel()
            for task in running:
                task.cancel()

    def _record(self, messages, tools, started, stats, result, usage, error, cancelled) -> None:
        tm = self.telemetry
        if tm is None:
            return
        prompt_chars = sum(len(json.dumps(m, ensure_ascii=False, default=str)) for m in messages)
        tm.emit(
            "llm.request",
            full={
                "last_message": messages[-1] if messages else None,
                "reply_text": result.text if result else None,
                "reply_tool_calls": [
                    {"name": t.name, "arguments": t.arguments} for t in (result.tool_calls if result else [])
                ],
            },
            provider=self.name,
            model=self.model,
            duration_ms=round((time.monotonic() - started) * 1000, 1),
            ok=error is None and not cancelled,
            error=error,
            cancelled=cancelled,
            n_messages=len(messages),
            n_tools=len(tools),
            prompt_chars=prompt_chars,
            reply_chars=len(result.text) if result else 0,
            reply_tools=[t.name for t in (result.tool_calls if result else [])],
            hedged=self.hedge_after_s is not None and stats["attempts"] > 1,
            usage=usage,
            **stats,
        )

    @staticmethod
    def _recover_failed_generation(response: httpx.Response) -> LLMResult | None:
        """Groq answers HTTP 400 `tool_use_failed` when a model mangles a tool call (wrong case, wrong wrapper)
        but still returns what it tried to generate. Hand that text back as JSON so the Core can re-read it."""
        try:
            error = response.json().get("error", {})
        except ValueError:
            return None
        if error.get("code") != "tool_use_failed":
            return None
        raw = str(error.get("failed_generation") or "")
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            args = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
        named = re.search(
            r"(?:function\s*=\s*|name['\"]?\s*[:=]\s*['\"]?)([A-Za-z_][\w.]*)", raw[:start] + raw[start : start + 60]
        )
        payload = {"name": named.group(1), "arguments": args} if named and "arguments" not in args else args
        return LLMResult(text=json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        header = response.headers.get("retry-after")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        try:
            msg = response.json().get("error", {}).get("message", "")
            digits = "".join(c if c.isdigit() else " " for c in msg).split()
            return float(digits[0]) if digits else 2.0
        except (ValueError, AttributeError):
            return 2.0

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


def _usage(response: httpx.Response) -> dict[str, Any] | None:
    try:
        raw = response.json().get("usage")
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    keep = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "queue_time",
        "prompt_time",
        "completion_time",
        "total_time",
    )
    return {k: raw[k] for k in keep if k in raw}


def from_env(env: dict[str, str] | None = None) -> OpenAICompatProvider:
    """Pick a provider from environment variables.

    WYSP_LLM_PROVIDER: groq | openrouter | cerebras | pollinations | openai | ollama | custom
    WYSP_LLM_MODEL, WYSP_LLM_BASE_URL, WYSP_LLM_API_KEY override the preset.
    Without WYSP_LLM_PROVIDER: the first provider whose key is present, else keyless Pollinations.
    """
    env = dict(os.environ) if env is None else env
    name = (env.get("WYSP_LLM_PROVIDER") or "").lower()
    if not name:
        for candidate in ("groq", "cerebras", "openrouter"):
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
        timeout_s=preset.timeout_s,
        hedge_after_s=preset.hedge_after_s,
        max_attempts=preset.max_attempts,
    )
