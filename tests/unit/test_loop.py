import pytest

from patchloop.agent import loop as loop_mod
from patchloop.agent.loop import Budget, run_episode
from patchloop.agent.models import FakeModel, FatalModelError, ModelTurn, RetryableModelError, ToolCall, Usage
from patchloop.agent.tools import Toolbox
from patchloop.agent.trajectory import Trajectory


def episode(env, script, budget=None, model=None, traj=None):
    return run_episode("bug", "pytest", model or FakeModel(script), Toolbox(env, "pytest"),
                       budget or Budget(max_steps=10), traj or Trajectory(), sleep=lambda s: None)


def test_submit_stops(mem_env):
    r = episode(mem_env, [{"calls": [("bash", {"command": "ls"})]}, {"calls": [("submit", {"summary": "s"})]}])
    assert (r.stop_reason, r.steps, r.submit_summary) == ("submitted", 2, "s")


def test_step_limit(mem_env):
    script = [{"calls": [("bash", {"command": f"echo {i}"})]} for i in range(20)]
    r = episode(mem_env, script, Budget(max_steps=4))
    assert (r.stop_reason, r.steps) == ("step_limit", 4)


def test_loop_detection_nudges_then_stops(mem_env):
    traj = Trajectory()
    r = episode(mem_env, [{"calls": [("bash", {"command": "ls"})]}] * 10, traj=traj)
    assert (r.stop_reason, r.steps) == ("loop_detected", 5)
    nudges = [o for rec in traj.records for o in rec.get("observations", []) if "nudge" in o]
    assert len(nudges) == 1  # exactly one nudge, at the third repeat


def test_no_tool_call_is_nudged(mem_env):
    traj = Trajectory()
    r = episode(mem_env, [{"text": "thinking out loud"}, {"calls": [("submit", {"summary": ""})]}], traj=traj)
    assert r.stop_reason == "submitted"
    assert "nudge" in traj.records[1]["observations"][0]


def test_refusal(mem_env):
    r = episode(mem_env, [{"text": "", "stop_reason": "refusal"}])
    assert r.stop_reason == "model_refusal"


class Flaky:
    model = "fake"

    def __init__(self, failures, exc=RetryableModelError):
        self.failures, self.exc, self.calls = failures, exc, 0

    def complete(self, system, messages, tools):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc("529 overloaded")
        return ModelTurn("", [ToolCall("1", "submit", {"summary": ""})], 0, Usage(10, 1), "tool_use")


def test_retries_then_succeeds(mem_env):
    m = Flaky(3)
    r = episode(mem_env, [], model=m)
    assert r.stop_reason == "submitted" and r.retries == 3 and m.calls == 4


def test_retries_exhausted_is_error(mem_env):
    r = episode(mem_env, [], model=Flaky(100), budget=Budget(max_retries=2))
    assert r.stop_reason == "error" and "gave up" in r.error


def test_fatal_error_stops_cleanly(mem_env):
    r = episode(mem_env, [], model=Flaky(1, FatalModelError))
    assert r.stop_reason == "error"


def test_cost_limit(mem_env, monkeypatch):
    monkeypatch.setattr(loop_mod, "cost_usd", lambda model, usage, pricing=None: 0.06)
    script = [{"calls": [("bash", {"command": f"echo {i}"})]} for i in range(10)]
    r = episode(mem_env, script, Budget(max_cost_usd=0.15))
    assert r.stop_reason == "cost_limit" and r.steps == 3


def test_time_limit(mem_env, monkeypatch):
    t = iter(range(0, 10_000, 400))
    monkeypatch.setattr(loop_mod.time, "monotonic", lambda: next(t))
    script = [{"calls": [("bash", {"command": f"echo {i}"})]} for i in range(10)]
    r = episode(mem_env, script, Budget(max_wall_s=600))
    assert r.stop_reason == "time_limit"


def test_tool_error_becomes_observation(mem_env):
    traj = Trajectory()
    episode(mem_env, [{"calls": [("view_file", {"path": "../../etc/passwd"})]}, {"calls": [("submit", {})]}], traj=traj)
    obs = traj.records[1]["observations"][0]
    assert obs["is_error"] and "outside /workspace" in obs["content"]


def test_history_is_append_only(mem_env):
    seen = []

    def spy(messages):
        seen.append(list(messages))
        return {"calls": [("bash", {"command": f"echo {len(messages)}"})]}

    episode(mem_env, [spy] * 4, Budget(max_steps=4))
    for earlier, later in zip(seen, seen[1:], strict=False):
        assert later[: len(earlier)] == earlier


def test_parallel_calls_all_get_results(mem_env):
    traj = Trajectory()
    episode(mem_env, [{"calls": [("bash", {"command": "a"}), ("submit", {}), ("bash", {"command": "b"})]}], traj=traj)
    obs = traj.records[1]["observations"]
    assert len(obs) == 3 and obs[2]["content"].startswith("Ignored")


@pytest.mark.parametrize("reason", loop_mod.STOP_REASONS)
def test_stop_reasons_known(reason):
    assert isinstance(reason, str)


def test_trajectory_has_required_fields(mem_env):
    traj = Trajectory()
    episode(mem_env, [{"calls": [("submit", {})]}], traj=traj)
    step = traj.records[1]
    for key in ("ts", "step", "text", "tool_calls", "observations", "usage", "cost_usd", "latency_s"):
        assert key in step
    assert traj.records[-1]["stop_reason"] == "submitted"
