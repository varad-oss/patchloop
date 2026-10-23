import json
from pathlib import Path

import anthropic
import openai
import pytest

from patchloop.agent.models import AnthropicAdapter, OpenAICompatibleAdapter, ToolSpec, Usage, cost_usd

FIX = Path(__file__).parents[1] / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


def test_anthropic_parse_by_type():
    msg = anthropic.types.Message.model_validate(load("anthropic_tool_use.json"))
    turn = AnthropicAdapter.parse(msg)
    assert turn.text == "Let me run the tests first."
    assert [c.name for c in turn.tool_calls] == ["run_tests", "search"]
    assert turn.tool_calls[1].args == {"pattern": "def median", "glob": "*.py"}
    assert turn.thinking_blocks == 1 and turn.stop_reason == "tool_use"
    assert turn.usage == Usage(120, 310, 250, 2048, 512)
    # The thinking block is kept byte-for-byte (empty text + signature) for replay.
    assert turn.raw[0] == {"type": "thinking", "thinking": "", "signature": "EqQBCkYIBxgCKkCfixture-signature"}


def test_anthropic_refusal():
    turn = AnthropicAdapter.parse(anthropic.types.Message.model_validate(load("anthropic_refusal.json")))
    assert turn.stop_reason == "refusal" and turn.tool_calls == []


def _adapter():
    return AnthropicAdapter(client=object())


def test_anthropic_request_surface():
    a = _adapter()
    req = a.request("SYS", [{"role": "user", "content": "hi"}], [ToolSpec("bash", "d", {"type": "object"})])
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in req
    assert req["thinking"] == {"type": "adaptive"} and req["output_config"] == {"effort": "low"}
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"} and req["cache_control"]
    assert req["messages"][-1]["role"] == "user"  # never an assistant prefill
    assert req["tools"][0]["input_schema"] == {"type": "object"}


def test_anthropic_wire_replays_thinking_and_merges_user_turns():
    raw = load("anthropic_tool_use.json")["content"]
    history = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "text": "", "tool_calls": [], "raw": raw},
        {"role": "tool", "results": [{"tool_call_id": "toolu_01A", "name": "run_tests", "content": "ok", "is_error": False},
                                     {"tool_call_id": "toolu_01B", "name": "search", "content": "x", "is_error": True}]},
        {"role": "user", "content": "nudge"},
    ]
    wire = _adapter().to_wire(history)
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    assert wire[1]["content"] is raw  # unchanged object, thinking block first
    assert [b["type"] for b in wire[2]["content"]] == ["tool_result", "tool_result", "text"]
    assert wire[2]["content"][1]["is_error"] is True


def test_openai_parallel_and_malformed_calls():
    resp = openai.types.chat.ChatCompletion.model_validate(load("openai_parallel.json"))
    turn = OpenAICompatibleAdapter.parse(resp)
    assert [c.name for c in turn.tool_calls] == ["view_file", "bash"]
    assert turn.tool_calls[0].args == {"path": "toyrepo/stats.py"} and turn.tool_calls[0].parse_error is None
    assert turn.tool_calls[1].parse_error and "invalid JSON" in turn.tool_calls[1].parse_error
    assert turn.usage.cache_read_tokens == 300 and turn.usage.input_tokens == 600
    assert turn.stop_reason == "tool_use"
    wire = OpenAICompatibleAdapter(model="m", client=object()).to_wire("S", [
        {"role": "assistant", "text": "", "tool_calls": turn.tool_calls, "raw": turn.raw},
        {"role": "tool", "results": [{"tool_call_id": "call_1", "name": "view_file", "content": "a", "is_error": False},
                                     {"tool_call_id": "call_2", "name": "bash", "content": "b", "is_error": True}]}])
    assert [m["role"] for m in wire] == ["system", "assistant", "tool", "tool"]


def test_cost_tiers():
    small = Usage(input_tokens=50_000, output_tokens=1_000_000)
    assert cost_usd("claude-haiku-5-5", small) == pytest.approx(0.005 + 0.50)
    big = Usage(input_tokens=150_000, output_tokens=0)  # > 100K prompt -> long-context card
    assert cost_usd("claude-haiku-5-5", big) == pytest.approx(150_000 * 0.50 / 1e6)
    cached = Usage(input_tokens=0, cache_read_tokens=50_000, cache_write_tokens=0)
    assert cost_usd("claude-haiku-5-5", cached) == pytest.approx(50_000 * 0.10 * 0.1 / 1e6)
    assert cost_usd("unknown-free-model", small) == 0.0


def test_ollama_route_is_free_and_local():
    from patchloop.agent.models import make_adapter
    from patchloop.cli import _is_paid

    a = make_adapter("ollama:patchloop-qwen3:8b-16k", effort="none")
    assert isinstance(a, OpenAICompatibleAdapter)
    assert a.model == "patchloop-qwen3:8b-16k" and a.reasoning_effort == "none"
    assert str(a.client.base_url).startswith("http://localhost:11434/v1")
    assert not _is_paid("ollama:patchloop-qwen3:8b-16k")
    assert _is_paid("claude-haiku-5-5")
    assert cost_usd(a.model, Usage(input_tokens=10_000, output_tokens=10_000)) == 0.0
