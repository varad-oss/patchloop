from patchloop.agent.context import ContextTracker, compact, last_observations
from patchloop.agent.loop import Budget, run_episode
from patchloop.agent.models import FakeModel
from patchloop.agent.tools import Toolbox
from patchloop.agent.trajectory import Trajectory


def test_tracker_anchors_on_reported_usage():
    t = ContextTracker(soft_limit=1000)
    msgs = [{"role": "user", "content": "x"}, {"role": "assistant", "text": "", "tool_calls": [], "raw": None}]
    t.record(prompt_tokens=900, messages_len_after_reply=2)
    assert not t.should_compact("", msgs, [])
    msgs.append({"role": "tool", "results": [{"content": "y" * 2000}]})
    assert t.should_compact("", msgs, [])


def test_compaction_starts_fresh_list_and_keeps_old_untouched():
    old = [{"role": "user", "content": "TASK"},
           {"role": "assistant", "text": "", "tool_calls": [], "raw": None},
           {"role": "tool", "results": [{"tool_call_id": "1", "name": "bash", "content": "obs1", "is_error": False}]},
           {"role": "assistant", "text": "", "tool_calls": [], "raw": None},
           {"role": "tool", "results": [{"tool_call_id": "2", "name": "bash", "content": "obs2", "is_error": False},
                                        {"tool_call_id": "3", "name": "bash", "content": "obs3", "is_error": False}]}]
    snapshot = [dict(m) for m in old]
    model = FakeModel([{"text": "SUMMARY: edited foo.py"}])
    fresh, turn = compact(model, "SYS", "TASK", old, [])
    assert old == snapshot
    assert len(fresh) == 1 and fresh[0]["role"] == "user"
    content = fresh[0]["content"]
    assert content.startswith("TASK") and "SUMMARY: edited foo.py" in content
    assert "obs2" in content and "obs3" in content and "obs1" not in content
    assert last_observations(old) == ["obs2", "obs3"]


def test_loop_compacts_when_over_soft_limit(mem_env):
    traj = Trajectory()
    big = "z" * 4000
    script = [{"calls": [("bash", {"command": f"echo {i} {big}"})]} for i in range(3)]
    script += [{"text": "summary of progress"}, {"calls": [("submit", {})]}]
    r = run_episode("bug", "pytest", FakeModel(script), Toolbox(mem_env, "pytest"),
                    Budget(max_steps=10, soft_prompt_tokens=2500), traj)
    assert r.compactions >= 1
    assert any(rec.get("event") == "compaction" for rec in traj.records)
    assert r.stop_reason == "submitted"
