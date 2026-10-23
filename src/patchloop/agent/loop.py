"""PatchLoop's agent loop - read it top to bottom.

Each step: build the request (system prompt + task + linear history) -> call the model through
the adapter -> execute the tool calls in the sandbox -> append truncated observations -> stop on
submit or any limit. History is append-only; compaction starts a fresh list instead of editing.

Grew out of seed/my_loop.py; docs/learning/LOOP_WALKTHROUGH.md explains every change.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from . import prompts
from .context import ContextTracker, compact
from .models import (
    FatalModelError,
    ModelAdapter,
    ModelTurn,
    RetryableModelError,
    Usage,
    cost_usd,
    load_pricing,
)
from .tools import Toolbox
from .trajectory import Trajectory

STOP_REASONS = ("submitted", "step_limit", "cost_limit", "time_limit", "model_refusal", "loop_detected", "error")


@dataclass
class Budget:
    max_steps: int = 40
    max_cost_usd: float = 0.15
    max_wall_s: float = 600.0
    soft_prompt_tokens: int = 80_000
    max_retries: int = 6


@dataclass
class EpisodeResult:
    stop_reason: str
    steps: int
    cost_usd: float
    usage: Usage
    wall_s: float
    compactions: int
    submit_summary: str = ""
    error: str = ""
    tool_errors: int = 0
    tool_calls: int = 0
    retries: int = 0

    def to_dict(self) -> dict:
        return {**asdict(self), "usage": asdict(self.usage)}


@dataclass
class LoopDetector:
    """Same action 3x in a row -> one nudge; 5x in a row -> stop."""

    nudge_at: int = 3
    stop_at: int = 5
    last: str = ""
    repeats: int = 0
    nudged: bool = False
    history: list[str] = field(default_factory=list)

    def observe(self, turn: ModelTurn) -> str:
        key = hashlib.sha256(json.dumps([(c.name, c.args) for c in turn.tool_calls], sort_keys=True,
                                        default=str).encode()).hexdigest()
        self.repeats = self.repeats + 1 if key == self.last else 1
        self.last = key
        if self.repeats >= self.stop_at:
            return "stop"
        if self.repeats >= self.nudge_at and not self.nudged:
            self.nudged = True
            return "nudge"
        if self.repeats == 1:
            self.nudged = False
        return "ok"


def call_with_retries(model: ModelAdapter, system: str, messages: list[dict], tools, budget: Budget,
                      sleep: Callable[[float], None], log: Callable[[dict], None]) -> tuple[ModelTurn, int]:
    """Retry 429 / 5xx / overloaded / connection errors with exponential backoff and jitter."""
    for attempt in range(budget.max_retries + 1):
        try:
            started = time.monotonic()
            turn = model.complete(system, messages, tools)
            turn.latency_s = round(time.monotonic() - started, 3)
            return turn, attempt
        except RetryableModelError as e:
            if attempt == budget.max_retries:
                raise FatalModelError(f"gave up after {attempt + 1} attempts: {e}") from e
            delay = e.retry_after or min(60.0, 2.0 * 2**attempt) * random.uniform(0.5, 1.5)
            log({"event": "retry", "attempt": attempt + 1, "delay_s": round(delay, 2), "error": str(e)[:300]})
            sleep(delay)
    raise AssertionError("unreachable")


def run_episode(problem_statement: str, test_cmd: str, model: ModelAdapter, toolbox: Toolbox,
                budget: Budget | None = None, traj: Trajectory | None = None,
                sleep: Callable[[float], None] = time.sleep) -> EpisodeResult:
    budget = budget or Budget()
    traj = traj or Trajectory()
    pricing = load_pricing()
    system = prompts.system_prompt(toolbox.toolset, budget.max_steps)
    specs = toolbox.specs()
    task_text = prompts.task_message(problem_statement, test_cmd)
    messages: list[dict] = [{"role": "user", "content": task_text}]

    tracker, detector = ContextTracker(budget.soft_prompt_tokens), LoopDetector()
    totals, cost, compactions, retries, tool_calls, tool_errors = Usage(), 0.0, 0, 0, 0, 0
    started = time.monotonic()
    traj.log({"event": "start", "model": model.model, "toolset": toolbox.toolset, "budget": asdict(budget),
              "system": system, "task": task_text})

    def finish(reason: str, step: int, summary: str = "", error: str = "") -> EpisodeResult:
        result = EpisodeResult(reason, step, round(cost, 6), totals, round(time.monotonic() - started, 2),
                               compactions, summary, error, tool_errors, tool_calls, retries)
        traj.log({"event": "end", "stop_reason": reason, **result.to_dict()})
        return result

    def account(turn: ModelTurn) -> float:
        nonlocal totals, cost
        call_cost = cost_usd(model.model, turn.usage, pricing)
        totals, cost = totals + turn.usage, cost + call_cost
        return call_cost

    for step in range(1, budget.max_steps + 1):
        if time.monotonic() - started > budget.max_wall_s:
            return finish("time_limit", step - 1)

        # 1. Context management: compact into a fresh list when the next prompt would be too big.
        if tracker.should_compact(system, messages, specs):
            try:
                messages, summary_turn = compact(model, system, task_text, messages, specs)
            except (FatalModelError, RetryableModelError) as e:
                return finish("error", step - 1, error=f"compaction failed: {e}")
            compactions += 1
            tracker.reset()
            traj.log({"event": "compaction", "step": step, "summary": summary_turn.text,
                      "usage": asdict(summary_turn.usage), "cost_usd": account(summary_turn)})

        # 2. Call the model (retries for transient errors happen inside).
        try:
            turn, attempts = call_with_retries(model, system, messages, specs, budget, sleep, traj.log)
        except FatalModelError as e:
            return finish("error", step - 1, error=str(e))
        retries += attempts
        call_cost = account(turn)
        messages.append({"role": "assistant", "text": turn.text, "tool_calls": turn.tool_calls, "raw": turn.raw})
        tracker.record(turn.usage.prompt_tokens, len(messages))
        record = {"event": "step", "step": step, "text": turn.text, "stop_reason_model": turn.stop_reason,
                  "thinking_blocks": turn.thinking_blocks, "tool_calls": [asdict(c) for c in turn.tool_calls],
                  "usage": asdict(turn.usage), "cost_usd": round(call_cost, 6), "latency_s": turn.latency_s}

        if turn.stop_reason == "refusal":
            traj.log({**record, "observations": []})
            return finish("model_refusal", step)

        # 3. No tool call: nudge (a step is still spent, so this cannot loop forever).
        if not turn.tool_calls:
            note = prompts.NO_TOOL_NUDGE
            if turn.stop_reason == "max_tokens":
                note = "Your reply hit the output token limit before any tool call. Be more concise. " + note
            messages.append({"role": "user", "content": note})
            traj.log({**record, "observations": [{"nudge": note}]})
            if cost >= budget.max_cost_usd:
                return finish("cost_limit", step)
            continue

        # 4. Execute tool calls in order, inside the sandbox. Errors come back as observations.
        results, observations, submitted, summary = [], [], False, ""
        for call in turn.tool_calls:
            if submitted:  # anything after submit is ignored, but every call still gets a result
                obs_text, is_error = "Ignored: submit was already called.", True
            else:
                obs = toolbox.execute(call)
                obs_text, is_error = obs.content, obs.is_error
                if obs.submitted:
                    submitted, summary = True, str(call.args.get("summary", ""))
            tool_calls += 1
            tool_errors += int(is_error)
            results.append({"tool_call_id": call.id, "name": call.name, "content": obs_text, "is_error": is_error})
            observations.append({"tool": call.name, "is_error": is_error, "content": obs_text})
        messages.append({"role": "tool", "results": results})

        # 5. Loop detection on the action itself.
        verdict = detector.observe(turn)
        if verdict == "nudge":
            messages.append({"role": "user", "content": prompts.LOOP_NUDGE})
            observations.append({"nudge": prompts.LOOP_NUDGE})
        traj.log({**record, "observations": observations})

        # 6. Stop conditions.
        if submitted:
            return finish("submitted", step, summary=summary)
        if verdict == "stop":
            return finish("loop_detected", step)
        if cost >= budget.max_cost_usd:
            return finish("cost_limit", step)
    return finish("step_limit", budget.max_steps)
