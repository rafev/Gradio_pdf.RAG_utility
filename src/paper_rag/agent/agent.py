"""Streaming agent loop.

A manual tool loop (rather than the SDK tool runner) so that every step can be forwarded to the
UI as it happens. Yields plain-dict events:

  {"type": "text", "delta", "round"}                 streamed answer text
  {"type": "round_end", "round", "has_tools"}        text of a round that ended in tool calls is interim
  {"type": "tool_call", "id", "name", "input", "round"}
  {"type": "tool_result", "id", "name", "summary", "is_error", "node_ids", "link_ids"}
  {"type": "citations", "passages": [...]}           passages the agent saw, keyed by chunk id
  {"type": "done", "usage", "node_ids", "link_ids", "model"}
  {"type": "error", "message"}
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from paper_rag.agent.prompts import SYSTEM_PROMPT
from paper_rag.agent.tools import ToolBox
from paper_rag.config import Settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 4000


def _history_messages(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Prior Q/A pairs as plain text (tool traffic isn't replayed; answers carry their citations)."""
    msgs: list[dict[str, Any]] = []
    for turn in history[-MAX_HISTORY_TURNS * 2 :]:
        role, content = turn.get("role"), turn.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        if msgs and msgs[-1]["role"] == role:  # keep strict alternation
            msgs[-1]["content"] += "\n\n" + content[:MAX_HISTORY_CHARS]
        else:
            msgs.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if msgs and msgs[-1]["role"] == "user":
        msgs.pop()
    return msgs


def _tools_with_cache(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools = [dict(t) for t in definitions]
    tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools


class Agent:
    def __init__(self, settings: Settings, toolbox: ToolBox, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self.toolbox = toolbox
        self.client = client or anthropic.AsyncAnthropic()
        self.tools = _tools_with_cache(toolbox.definitions)
        self.system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

    def _stream(self, messages: list[dict[str, Any]], final_round: bool):
        kwargs: dict[str, Any] = dict(
            model=self.settings.agent_model,
            max_tokens=16000,
            system=self.system,
            tools=self.tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self.settings.agent_effort},
            cache_control={"type": "ephemeral"},  # also cache the growing conversation between rounds
        )
        if final_round:
            kwargs["tool_choice"] = {"type": "none"}
        if self.settings.enable_fallbacks:
            return self.client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return self.client.messages.stream(**kwargs)

    async def run(self, question: str, history: list[dict[str, str]] | None = None) -> AsyncIterator[dict[str, Any]]:
        messages: list[dict[str, Any]] = [*_history_messages(history or []), {"role": "user", "content": question}]
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        node_ids: dict[str, None] = {}
        link_ids: dict[str, None] = {}
        passages: dict[str, dict[str, Any]] = {}
        model = self.settings.agent_model
        max_rounds = self.settings.agent_max_tool_rounds

        try:
            for round_n in range(max_rounds + 1):
                final_round = round_n == max_rounds
                if final_round:
                    messages.append({"role": "user", "content": "Tool budget reached. Answer now with what you have."})
                async with self._stream(messages, final_round) as stream:
                    async for event in stream:
                        if event.type == "text":
                            yield {"type": "text", "delta": event.text, "round": round_n}
                    response = await stream.get_final_message()

                model = response.model
                for key in usage:
                    usage[key] += getattr(response.usage, key, 0) or 0

                if response.stop_reason == "refusal":
                    yield {"type": "error", "message": "The model declined to answer this question."}
                    break
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                yield {"type": "round_end", "round": round_n, "has_tools": bool(tool_uses)}
                if not tool_uses:
                    if response.stop_reason == "max_tokens":
                        yield {"type": "error", "message": "The answer was cut off (output limit reached)."}
                    break
                if response.stop_reason == "max_tokens":
                    yield {"type": "error", "message": "A tool call was cut off (output limit reached)."}
                    break

                messages.append({"role": "assistant", "content": response.content})
                for tu in tool_uses:
                    yield {"type": "tool_call", "id": tu.id, "name": tu.name, "input": tu.input, "round": round_n}

                outputs = await asyncio.gather(*(asyncio.to_thread(self.toolbox.run, tu.name, tu.input) for tu in tool_uses))
                results = []
                for tu, out in zip(tool_uses, outputs):
                    node_ids.update(dict.fromkeys(out.node_ids))
                    link_ids.update(dict.fromkeys(out.link_ids))
                    for p in out.passages:
                        passages[p["chunk_id"]] = p
                    yield {"type": "tool_result", "id": tu.id, "name": tu.name, "summary": out.summary,
                           "is_error": out.is_error, "node_ids": out.node_ids, "link_ids": out.link_ids}
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out.content,
                                    **({"is_error": True} if out.is_error else {})})
                messages.append({"role": "user", "content": results})
        except anthropic.RateLimitError:
            yield {"type": "error", "message": "Rate limited by the Claude API. Please try again shortly."}
        except anthropic.APIStatusError as exc:
            log.exception("Claude API error")
            yield {"type": "error", "message": f"Claude API error ({exc.status_code})."}
        except anthropic.APIConnectionError:
            yield {"type": "error", "message": "Could not reach the Claude API."}

        yield {"type": "citations", "passages": list(passages.values())}
        yield {"type": "done", "usage": usage, "node_ids": list(node_ids), "link_ids": list(link_ids), "model": model}
