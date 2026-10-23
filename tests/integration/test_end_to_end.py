"""A scripted FakeModel fixes the toy bug end to end in Docker; the grader agrees."""

import json
from pathlib import Path

import pytest

from patchloop.agent.loop import run_episode
from patchloop.agent.models import FakeModel
from patchloop.agent.tools import Toolbox
from patchloop.agent.trajectory import Trajectory
from patchloop.evals.grader import grade
from patchloop.evals.runner import giveup_model, oracle_model
from patchloop.sandbox.docker_env import DockerEnv
from patchloop.sandbox.local_env import TOY_REPO, UnsafeLocalEnv

pytestmark = pytest.mark.docker
TASK = json.loads((Path(__file__).parents[2] / "bench" / "toy" / "toy__median-even.json").read_text())
FIX = {"path": "toyrepo/stats.py", "old_str": "(ordered[mid] + ordered[mid + 1])",
       "new_str": "(ordered[mid - 1] + ordered[mid])"}
SCRIPT = [
    {"calls": [("run_tests", {})]},
    {"calls": [("search", {"pattern": "def median"})]},
    {"calls": [("view_file", {"path": "toyrepo/stats.py"})]},
    {"calls": [("str_replace", FIX)]},
    {"calls": [("run_tests", {})]},
    {"calls": [("submit", {"summary": "average mid-1 and mid"})]},
]


def test_fake_model_fixes_toy_bug_in_docker(tmp_path):
    traj = Trajectory(tmp_path / "t.jsonl")
    with DockerEnv(TASK["image"], TASK["tests_dir"], TASK["bug_patch"]) as env:
        r = run_episode(TASK["problem_statement"], TASK["test_cmd"], FakeModel(SCRIPT), Toolbox(env, TASK["test_cmd"]),
                        traj=traj)
        patch = env.diff()
    assert r.stop_reason == "submitted" and r.tool_errors == 0
    first_tests = traj.records[1]["observations"][0]["content"]
    assert "1 failed, 5 passed" in first_tests
    assert "6 passed" in traj.records[5]["observations"][0]["content"]
    assert "def median" in traj.records[2]["observations"][0]["content"]
    assert "17\t    return (ordered[mid] + ordered[mid + 1]) / 2" in traj.records[3]["observations"][0]["content"]
    g = grade(TASK, patch)
    assert g["resolved"], g


def test_grader_rejects_unfixed_and_oracle_resolves():
    assert grade(TASK, "")["reason"] == "empty_patch"
    wrong = TASK["bug_patch"].replace("toyrepo/stats.py", "toyrepo/stats.py")  # re-applying the bug can't apply
    assert not grade(TASK, wrong)["resolved"]


def test_oracle_and_giveup_models(tmp_path):
    for factory, expect in ((oracle_model, True), (giveup_model, False)):
        with DockerEnv(TASK["image"], TASK["tests_dir"], TASK["bug_patch"]) as env:
            run_episode(TASK["problem_statement"], TASK["test_cmd"], factory(TASK), Toolbox(env, TASK["test_cmd"]))
            patch = env.diff()
        assert grade(TASK, patch)["resolved"] is expect


def test_unsafe_local_mode_on_toy_repo():
    with UnsafeLocalEnv(TOY_REPO, TASK["tests_dir"], TASK["bug_patch"], unsafe_local=True) as env:
        r = run_episode(TASK["problem_statement"], TASK["test_cmd"], FakeModel(SCRIPT), Toolbox(env, TASK["test_cmd"]))
        assert r.stop_reason == "submitted"
        assert "ordered[mid - 1]" in env.diff()
