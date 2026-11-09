"""The tutoring turn: build context, let the LLM call tools, narrate, stop on cancel."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from ..llm import CancelToken, LLMError, LLMResult
from .context import build_system_prompt
from .tools import ToolBox, recover_tool_call

if TYPE_CHECKING:
    from ..session.session import Session

log = logging.getLogger("wysp.turn")

MAX_ROUNDS = 8
HISTORY_LIMIT = 12
LLM_RETRY_DELAY_S = 1.5


class TurnRunner:
    def __init__(self, session: Session, cancel: CancelToken) -> None:
        self.s = session
        self.cancel = cancel

    async def run(self, user_text: str) -> None:
        s = self.s
        s.narration.new_turn()
        await s.set_status("thinking")
        try:
            system = await build_system_prompt(s)
            toolbox = ToolBox(s)
            tools = toolbox.specs()
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system},
                *s.history[-HISTORY_LIMIT:],
                {"role": "user", "content": user_text},
            ]
            for _ in range(MAX_ROUNDS):
                if self.cancel.cancelled:
                    return
                result = await self._complete(messages, tools)
                if self.cancel.cancelled:
                    return
                if result.text and not result.tool_calls:
                    recovered = recover_tool_call(result.text, {t.name for t in tools})
                    if recovered is not None:
                        log.info("recovered a %s call that the model wrote as text", recovered.name)
                        result = LLMResult(text="", tool_calls=[recovered])
                log.info(
                    "round: text=%r tools=%s",
                    result.text[:80],
                    [(tc.name, json.dumps(tc.arguments, ensure_ascii=False)[:110]) for tc in result.tool_calls],
                )
                if result.text and not (result.tool_calls and toolbox.narrated):
                    # Plain text from the model is narrated, so free models that skip `narrate` still work.
                    await s.narrate(result.text)
                if not result.tool_calls:
                    break
                messages.append(self._assistant_message(result))
                for tc in result.tool_calls:
                    if self.cancel.cancelled:
                        return
                    out = await toolbox.call(tc.name, tc.arguments)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "content": json.dumps(out, ensure_ascii=False)[:6000],
                        }
                    )
                if toolbox.turn_ended:
                    break
            else:
                await s.narrate("I stopped here to keep things simple. Tell me what you would like to look at next.")
            spoken = " ".join(seg.text for seg in s.narration.segments)
            s.history += [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": spoken or "(no answer)"},
            ]
            del s.history[: max(0, len(s.history) - HISTORY_LIMIT)]
        except LLMError as exc:
            log.warning("LLM failure: %s", exc)
            await s.narrate("I could not reach my language model just now. Please try again in a moment.")
            await s.activity(f"LLM error: {exc}")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("turn failed")
            await s.narrate("Something went wrong on my side. Please try again.")
        finally:
            if not s.narration.segments or all(seg.id in s.narration.played for seg in s.narration.segments):
                await s.set_status("idle")
            elif s.status == "thinking":
                await s.set_status("speaking")

    async def _complete(self, messages: list[dict[str, Any]], tools: list) -> LLMResult:
        try:
            return await self.s.llm.complete(messages, tools, self.cancel)
        except LLMError:
            if self.cancel.cancelled:
                return LLMResult()
            await asyncio.sleep(LLM_RETRY_DELAY_S)
            return await self.s.llm.complete(messages, tools, self.cancel)

    @staticmethod
    def _assistant_message(result: LLMResult) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": result.text or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                }
                for tc in result.tool_calls
            ],
        }
