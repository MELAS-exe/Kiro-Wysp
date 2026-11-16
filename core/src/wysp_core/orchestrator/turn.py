"""The tutoring turn: build context, let the LLM call tools, narrate, stop on cancel.

Every turn is measured (telemetry kind `turn`): total time, time spent waiting for the LLM, time spent in
tools, time to the first spoken segment, number of rounds and the outcome.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from ..llm import CancelToken, LLMError, LLMResult
from .context import build_system_prompt
from .tools import ToolBox, normalize_tool_name, recover_tool_call

if TYPE_CHECKING:
    from ..session.session import Session

log = logging.getLogger("wysp.turn")

MAX_ROUNDS = 8
HISTORY_LIMIT = 12
LLM_RETRY_DELAY_S = 1.5
# Tools whose result the model does not need to see before finishing its turn.
DISPLAY_TOOLS = {"narrate", "show_entities", "add_concept", "annotate", "highlight", "clear_highlight"}
GIST_CHARS = 280


def _gist(text: str) -> str:
    """A past reply shortened for the history (first sentences, at most GIST_CHARS)."""
    text = " ".join(text.split())
    if len(text) <= GIST_CHARS:
        return text
    cut = text[:GIST_CHARS]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return (cut[: end + 1] if end > GIST_CHARS // 2 else cut.rstrip()) + " …"


class TurnRunner:
    def __init__(self, session: Session, cancel: CancelToken) -> None:
        self.s = session
        self.cancel = cancel
        self.llm_ms = 0.0
        self.tool_ms = 0.0
        self.rounds = 0

    async def run(self, user_text: str) -> None:
        s = self.s
        t0 = time.monotonic()
        s.narration.new_turn()
        s.first_segment_t = None
        outcome = "ok"
        await s.set_status("thinking")
        try:
            t_ctx = time.monotonic()
            system = await build_system_prompt(s)
            context_ms = round((time.monotonic() - t_ctx) * 1000, 1)
            toolbox = ToolBox(s, self.cancel)
            tools = toolbox.specs()
            s.tm.emit(
                "turn.start",
                full={"user_text": user_text, "system_prompt": system},
                context_ms=context_ms,
                system_chars=len(system),
                n_tools=len(tools),
                history=len(s.history),
            )
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system},
                *s.history[-HISTORY_LIMIT:],
                {"role": "user", "content": user_text},
            ]
            for _ in range(MAX_ROUNDS):
                if self.cancel.cancelled:
                    outcome = "cancelled"
                    return
                self.rounds += 1
                t_llm = time.monotonic()
                result = await self._complete(messages, tools)
                self.llm_ms += (time.monotonic() - t_llm) * 1000
                if self.cancel.cancelled:
                    outcome = "cancelled"
                    return
                recovered_from_text = False
                if result.text and not result.tool_calls:
                    recovered = recover_tool_call(result.text, {t.name for t in tools})
                    if recovered is not None:
                        recovered_from_text = True
                        log.info("recovered a %s call that the model wrote as text", recovered.name)
                        s.tm.emit("llm.recovered_tool_call", full={"text": result.text}, tool=recovered.name)
                        result = LLMResult(text="", tool_calls=[recovered])
                s.tm.emit(
                    "llm.round",
                    full={
                        "text": result.text,
                        "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls],
                    },
                    round=self.rounds,
                    text_chars=len(result.text),
                    tools=[tc.name for tc in result.tool_calls],
                    recovered_from_text=recovered_from_text,
                )
                if result.text and not (result.tool_calls and toolbox.narrated):
                    # Plain text from the model is narrated, so free models that skip `narrate` still work.
                    await s.narrate(result.text)
                if not result.tool_calls:
                    break
                messages.append(self._assistant_message(result))
                for tc in result.tool_calls:
                    if self.cancel.cancelled:
                        outcome = "cancelled"
                        return
                    t_tool = time.monotonic()
                    out = await toolbox.call(tc.name, tc.arguments)
                    self.tool_ms += (time.monotonic() - t_tool) * 1000
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
                names = {normalize_tool_name(tc.name) for tc in result.tool_calls}
                if "narrate" in names and names <= DISPLAY_TOOLS:
                    # Wysp has spoken and nothing in this round needs a reaction: one more LLM request would
                    # only add a sentence, and on rate-limited free tiers it costs seconds.
                    break
            else:
                outcome = "max_rounds"
                await s.narrate("I stopped here to keep things simple. Tell me what you would like to look at next.")
            spoken = " ".join(seg.text for seg in s.narration.segments)
            s.history += [
                {"role": "user", "content": user_text},
                # Older replies only need their gist: every request carries the history, and free LLM tiers
                # are limited in tokens per minute (each saved token is latency saved).
                {"role": "assistant", "content": _gist(spoken) or "(no answer)"},
            ]
            del s.history[: max(0, len(s.history) - HISTORY_LIMIT)]
        except LLMError as exc:
            outcome = "llm_error"
            log.warning("LLM failure: %s", exc)
            await s.narrate("I could not reach my language model just now. Please try again in a moment.")
            await s.activity(f"LLM error: {exc}")
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:  # noqa: BLE001
            outcome = "error"
            log.exception("turn failed")
            await s.narrate("Something went wrong on my side. Please try again.")
        finally:
            first = s.first_segment_t
            s.tm.emit(
                "turn",
                full={"spoken": " ".join(seg.text for seg in s.narration.segments)},
                duration_ms=round((time.monotonic() - t0) * 1000, 1),
                llm_ms=round(self.llm_ms, 1),
                tool_ms=round(self.tool_ms, 1),
                rounds=self.rounds,
                first_segment_ms=round((first - t0) * 1000, 1) if first else None,
                segments=len(s.narration.segments),
                spoken_chars=sum(len(seg.text) for seg in s.narration.segments),
                outcome=outcome,
                ok=outcome in ("ok", "cancelled"),
            )
            if not s.narration.segments or all(seg.id in s.narration.played for seg in s.narration.segments):
                await s.set_status("idle")
            elif s.status == "thinking":
                await s.set_status("speaking")

    async def _complete(self, messages: list[dict[str, Any]], tools: list) -> LLMResult:
        try:
            return await self.s.llm.complete(messages, tools, self.cancel)
        except LLMError as exc:
            if self.cancel.cancelled:
                return LLMResult()
            self.s.tm.emit("llm.retry", reason=str(exc)[:200], delay_s=LLM_RETRY_DELAY_S)
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
