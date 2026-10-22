"""Context management: count prompt tokens, and compact by starting a fresh message list.

Token counting: the API reports the exact prompt size of every call in `usage`. The tracker
anchors on that number and adds an approximation (chars / 3.5) only for the messages appended
since - so the estimate is exact up to the newest observations. The approximation is
documented in docs/DECISIONS.md (ADR-006); it errs on the high side for code.
"""

from __future__ import annotations

import json

from . import prompts
from .models import ModelAdapter, ModelTurn, ToolSpec

CHARS_PER_TOKEN = 3.5


def approx_tokens(obj: object) -> int:
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return int(len(text) / CHARS_PER_TOKEN) + 1


class ContextTracker:
    def __init__(self, soft_limit: int):
        self.soft_limit = soft_limit
        self.anchor_tokens = 0  # exact prompt tokens of the last call
        self.anchor_len = 0  # len(messages) at that call, plus the assistant turn it produced

    def record(self, prompt_tokens: int, messages_len_after_reply: int) -> None:
        self.anchor_tokens = prompt_tokens
        self.anchor_len = messages_len_after_reply

    def reset(self) -> None:
        self.anchor_tokens = self.anchor_len = 0

    def estimate(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> int:
        if self.anchor_tokens == 0:
            return approx_tokens(system) + approx_tokens([t.__dict__ for t in tools]) + approx_tokens(messages)
        return self.anchor_tokens + approx_tokens(messages[self.anchor_len - 1:])

    def should_compact(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> bool:
        return self.estimate(system, messages, tools) > self.soft_limit


def last_observations(messages: list[dict], n: int = 2, max_chars: int = 4000) -> list[str]:
    found: list[str] = []
    for m in reversed(messages):
        if m["role"] == "tool":
            for r in reversed(m["results"]):
                found.append(r["content"][:max_chars])
                if len(found) == n:
                    return list(reversed(found))
    return list(reversed(found))


def compact(model: ModelAdapter, system: str, task_text: str, messages: list[dict],
            tools: list[ToolSpec]) -> tuple[list[dict], ModelTurn]:
    """Ask the model for a progress summary, then return a FRESH message list.

    The old list is never edited: the summary request is appended to it (append-only), and the
    new list starts over with system prompt + task + summary + the last two observations.
    The same tools are sent so the request is valid for a history that contains tool calls.
    """
    request = [*messages, {"role": "user", "content": prompts.COMPACTION_REQUEST}]
    turn = model.complete(system, request, tools)
    summary = turn.text.strip() or "(the model returned an empty summary)"
    fresh = [{"role": "user", "content": prompts.compacted_message(task_text, summary, last_observations(messages))}]
    return fresh, turn
