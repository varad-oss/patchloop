"""Day-1 seed loop: the smallest agent loop that can fix a failing test.

Authorship: the original plan was for Varad to hand-write this file on Day 1. It was written by
Claude (Claude Code) instead, in the same spirit (~120 lines, no framework), and on 2026-10-24
Varad chose to keep it rather than replace it. src/patchloop/agent/loop.py grew out of it, and
docs/learning/LOOP_WALKTHROUGH.md maps every change.

It is kept for reference only. It is never imported, and it does not execute anything itself:
the caller passes `run_bash`, which in PatchLoop always goes to a Docker container.
"""

import json
import time

import anthropic

MODEL = "claude-haiku-5-5"
MAX_STEPS = 30

SYSTEM = """You are a careful software engineer. A Python repository has failing tests.
Use the bash tool to explore, edit files and run the tests. When the tests pass, call submit.
Never edit the tests."""

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command in the repository root and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "submit",
        "description": "Call when you are done. The current diff is your answer.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]


def truncate(text, head=100, tail=50):
    lines = text.splitlines()
    if len(lines) <= head + tail:
        return text
    cut = len(lines) - head - tail
    return "\n".join(lines[:head] + [f"[... {cut} lines truncated ...]"] + lines[-tail:])


def call_model(client, messages):
    # Retry transient errors with exponential backoff; give up on anything else.
    for attempt in range(5):
        try:
            return client.messages.create(
                model=MODEL,
                max_tokens=8000,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError):
            time.sleep(2**attempt)
    raise RuntimeError("model unavailable")


def run(task_text, run_bash):
    """run_bash(command) -> (exit_code, output). Returns (stop_reason, steps)."""
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": task_text}]
    for step in range(1, MAX_STEPS + 1):
        response = call_model(client, messages)
        # Append the whole content list (thinking blocks included) - never just the text.
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "refusal":
            return "model_refusal", step

        results = []
        submitted = False
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit":
                submitted = True
                output, is_error = "submitted", False
            elif block.name == "bash":
                code, out = run_bash(block.input["command"])
                output, is_error = f"exit_code: {code}\n{truncate(out)}", False
            else:
                output, is_error = f"unknown tool {block.name}", True
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error}
            )
            print(json.dumps({"step": step, "tool": block.name, "input": block.input})[:200])

        if submitted:
            return "submitted", step
        if not results:
            messages.append({"role": "user", "content": "Please continue using the tools, or call submit."})
        else:
            messages.append({"role": "user", "content": results})
    return "step_limit", MAX_STEPS
