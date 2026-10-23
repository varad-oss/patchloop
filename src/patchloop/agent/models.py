"""Model adapters: one small protocol, three implementations (Anthropic, OpenAI-compatible, Fake).

The loop speaks a provider-neutral history:
    {"role": "user", "content": str}
    {"role": "assistant", "text": str, "tool_calls": [ToolCall...], "raw": <provider content>}
    {"role": "tool", "results": [{"tool_call_id", "name", "content", "is_error"}]}
Each adapter converts that history to its wire format. `raw` keeps the provider's assistant
content byte-for-byte (thinking blocks and their signatures included), so it can be replayed
unchanged - required by Claude models that bind thinking blocks to the exact history.
"""

from __future__ import annotations

import json
import tomllib
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

PRICING_PATH = Path(__file__).resolve().parents[3] / "config" / "pricing.toml"


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    parse_error: str | None = None  # set when the model emitted arguments that are not valid JSON


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0  # a subset of output_tokens
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(*(a + b for a, b in zip(asdict(self).values(), asdict(other).values(), strict=True)))


@dataclass
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    thinking_blocks: int
    usage: Usage
    stop_reason: str  # normalised: end_turn | tool_use | max_tokens | refusal | other
    raw: Any = None
    latency_s: float = 0.0


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema


class RetryableModelError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class FatalModelError(Exception):
    pass


class ModelAdapter(Protocol):
    model: str

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> ModelTurn: ...


# ---------------------------------------------------------------- pricing


def load_pricing(path: Path = PRICING_PATH) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def cost_usd(model: str, usage: Usage, pricing: dict | None = None) -> float:
    """Cost of one call, from the usage the API returned. Unknown models cost 0 (free tiers)."""
    table = (pricing or load_pricing())["models"].get(model)
    if table is None:
        return 0.0
    in_rate, out_rate = table["input"], table["output"]
    threshold = table.get("long_context_threshold")
    if threshold and usage.prompt_tokens > threshold:
        in_rate, out_rate = table["long_input"], table["long_output"]
    total = (
        usage.input_tokens * in_rate
        + usage.cache_read_tokens * in_rate * table.get("cache_read_mult", 1.0)
        + usage.cache_write_tokens * in_rate * table.get("cache_write_mult", 1.0)
        + usage.output_tokens * out_rate
    )
    return total / 1_000_000


# ---------------------------------------------------------------- Anthropic


def _retry_after(err: Exception) -> float | None:
    response = getattr(err, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return float(value) if value else None
    except ValueError:
        return None


class AnthropicAdapter:
    """Native tool use on the Messages API, written for Claude Haiku 5.5's request surface:
    adaptive thinking (always on), depth set by output_config.effort, no sampling parameters,
    no prefill, content read by block type, thinking blocks replayed unchanged."""

    def __init__(self, model: str = "claude-haiku-5-5", effort: str = "low", max_tokens: int = 16000,
                 client: Any = None):
        import anthropic

        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens  # thinking tokens count toward this cap
        # SDK retries are off: the loop owns retries so they are visible in the trajectory.
        self.client = client or anthropic.Anthropic(max_retries=0, timeout=300)
        self._anthropic = anthropic

    def to_wire(self, messages: list[dict]) -> list[dict]:
        wire: list[dict] = []
        for m in messages:
            if m["role"] == "assistant":
                wire.append({"role": "assistant", "content": m["raw"]})
                continue
            if m["role"] == "user":
                blocks = [{"type": "text", "text": m["content"]}]
            else:
                blocks = [
                    {"type": "tool_result", "tool_use_id": r["tool_call_id"], "content": r["content"],
                     "is_error": r["is_error"]}
                    for r in m["results"]
                ]
            if wire and wire[-1]["role"] == "user":  # tool results + a nudge become one user turn
                wire[-1]["content"].extend(blocks)
            else:
                wire.append({"role": "user", "content": blocks})
        return wire

    def request(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> dict:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # Breakpoint 1: tools + system (stable for the whole episode).
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                      for t in tools],
            "messages": self.to_wire(messages),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            # Breakpoint 2 (automatic): the end of the append-only history.
            "cache_control": {"type": "ephemeral"},
        }

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> ModelTurn:
        a = self._anthropic
        try:
            response = self.client.messages.create(**self.request(system, messages, tools))
        except (a.RateLimitError, a.InternalServerError, a.APIConnectionError) as e:
            raise RetryableModelError(f"{type(e).__name__}: {e}", _retry_after(e)) from e
        except a.APIStatusError as e:
            if e.status_code in (408, 409, 429) or e.status_code >= 500:  # incl. 529 overloaded
                raise RetryableModelError(f"{e.status_code}: {e}", _retry_after(e)) from e
            raise FatalModelError(f"{e.status_code}: {e}") from e
        return self.parse(response)

    @staticmethod
    def parse(response: Any) -> ModelTurn:
        text, calls, thinking = [], [], 0
        for block in response.content:  # read by type, never by position
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input or {})))
            elif block.type in ("thinking", "redacted_thinking"):
                thinking += 1
        u = response.usage
        details = getattr(u, "output_tokens_details", None)
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            thinking_tokens=getattr(details, "thinking_tokens", 0) or 0,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
        )
        stop = response.stop_reason if response.stop_reason in (
            "end_turn", "tool_use", "max_tokens", "refusal") else "other"
        raw = [b.model_dump(mode="json", exclude_none=True) for b in response.content]
        return ModelTurn("\n".join(text), calls, thinking, usage, stop, raw)


# ---------------------------------------------------------------- OpenAI-compatible


class OpenAICompatibleAdapter:
    """Chat Completions function calling, for free/local models (Ollama, Groq, OpenRouter, Gemini's endpoint).

    reasoning_effort is passed through when set; Ollama maps "none" to thinking off for qwen3."""

    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None,
                 max_tokens: int = 8000, client: Any = None, reasoning_effort: str | None = None,
                 timeout: float = 300):
        import openai

        self.model = model
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.client = client or openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=timeout)
        self._openai = openai

    def to_wire(self, system: str, messages: list[dict]) -> list[dict]:
        wire: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                wire.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                wire.append(m["raw"])
            else:
                wire.extend({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]}
                            for r in m["results"])
        return wire

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> ModelTurn:
        o = self._openai
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=self.to_wire(system, messages),
                tools=[{"type": "function", "function": {"name": t.name, "description": t.description,
                                                         "parameters": t.parameters}} for t in tools],
                **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
            )
        except (o.RateLimitError, o.InternalServerError, o.APIConnectionError) as e:
            raise RetryableModelError(f"{type(e).__name__}: {e}", _retry_after(e)) from e
        except o.APIStatusError as e:
            if e.status_code in (408, 409, 429) or e.status_code >= 500:
                raise RetryableModelError(f"{e.status_code}: {e}", _retry_after(e)) from e
            raise FatalModelError(f"{e.status_code}: {e}") from e
        return self.parse(response)

    @staticmethod
    def parse(response: Any) -> ModelTurn:
        choice = response.choices[0]
        msg = choice.message
        calls: list[ToolCall] = []
        raw_calls = []
        for tc in msg.tool_calls or []:  # parallel tool calls arrive as a list
            raw_args = tc.function.arguments or "{}"
            try:
                args, err = json.loads(raw_args), None
                if not isinstance(args, dict):
                    args, err = {}, f"arguments must be a JSON object, got {raw_args[:200]!r}"
            except json.JSONDecodeError as e:
                args, err = {}, f"invalid JSON arguments ({e.msg}): {raw_args[:200]!r}"
            call_id = tc.id or f"call_{uuid.uuid4().hex[:12]}"
            calls.append(ToolCall(call_id, tc.function.name, args, err))
            raw_calls.append({"id": call_id, "type": "function",
                              "function": {"name": tc.function.name, "arguments": raw_args}})
        raw: dict = {"role": "assistant", "content": msg.content or ""}
        if raw_calls:
            raw["tool_calls"] = raw_calls
        u = response.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0 if u else 0
        reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0 if u else 0
        usage = Usage(
            input_tokens=(u.prompt_tokens - cached) if u else 0,
            output_tokens=u.completion_tokens if u else 0,
            thinking_tokens=reasoning,
            cache_read_tokens=cached,
        )
        stop = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens",
                "content_filter": "refusal"}.get(choice.finish_reason, "other")
        return ModelTurn(msg.content or "", calls, 0, usage, stop, raw)


# ---------------------------------------------------------------- Fake (scripted)


@dataclass
class FakeModel:
    """Replays a script of turns. Each entry is a dict {"text": str, "calls": [(name, args), ...]}
    or a callable(messages) -> such a dict. When the script runs out it submits."""

    script: list[dict | Callable[[list[dict]], dict]] = field(default_factory=list)
    model: str = "fake"
    calls_made: int = 0

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> ModelTurn:
        entry = self.script[self.calls_made] if self.calls_made < len(self.script) else {
            "text": "Out of script.", "calls": [("submit", {"summary": "fake model finished"})]}
        self.calls_made += 1
        if callable(entry):
            entry = entry(messages)
        calls = [ToolCall(f"fake_{self.calls_made}_{i}", name, dict(args))
                 for i, (name, args) in enumerate(entry.get("calls", []))]
        prompt_chars = len(system) + sum(len(json.dumps(m, default=str)) for m in messages)
        usage = Usage(input_tokens=prompt_chars // 4, output_tokens=20)
        raw = {"text": entry.get("text", ""), "calls": [(c.name, c.args) for c in calls]}
        return ModelTurn(entry.get("text", ""), calls, 0, usage,
                         entry.get("stop_reason", "tool_use" if calls else "end_turn"), raw)


def make_adapter(spec: str, effort: str = "low") -> ModelAdapter:
    """'claude-haiku-5-5' -> Anthropic; 'openai:<model>' -> OpenAI-compatible (env-configured);
    'ollama:<model>' -> a local Ollama server (free, no key). For Ollama, effort 'none' turns thinking off."""
    import os

    if spec.startswith("ollama:"):
        return OpenAICompatibleAdapter(spec.removeprefix("ollama:"),
                                       base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                                       api_key="ollama", reasoning_effort=effort, timeout=600)
    if spec.startswith("openai:"):
        return OpenAICompatibleAdapter(spec.removeprefix("openai:"),
                                       base_url=os.environ.get("OPENAI_COMPAT_BASE_URL"),
                                       api_key=os.environ.get("OPENAI_COMPAT_API_KEY"))
    if spec == "fake":
        return FakeModel()
    return AnthropicAdapter(spec, effort=effort)
