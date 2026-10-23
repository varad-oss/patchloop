"""Safety properties that need no Docker daemon: argv shape, flags, secrets, the unsafe-local gate."""

import subprocess
from pathlib import Path

import pytest

from patchloop.agent.models import ToolCall
from patchloop.agent.tools import Toolbox
from patchloop.agent.trajectory import Trajectory, redact
from patchloop.sandbox import docker_env
from patchloop.sandbox.docker_env import DockerEnv, _run_docker
from patchloop.sandbox.local_env import TOY_REPO, UnsafeLocalEnv


def test_run_docker_refuses_host_commands():
    with pytest.raises(AssertionError):
        _run_docker(["bash", "-c", "echo pwned"])
    with pytest.raises(AssertionError):
        _run_docker(["docker", "system", "prune", "-af"])


def test_isolation_flags_present():
    argv = DockerEnv("img", "tests").run_argv(Path("/host/tests"))
    joined = " ".join(argv)
    for flag in ["--network none", "--memory 1g", "--memory-swap 1g", "--cpus 1", "--pids-limit 256",
                 "--read-only", "--tmpfs /tmp:", "--user 1000:1000", "--security-opt no-new-privileges",
                 "--cap-drop ALL", "--rm", "dst=/workspace/tests,readonly"]:
        assert flag in joined, flag
    assert "-e" not in argv and "--env" not in argv and "--privileged" not in argv  # no secrets, no privilege


def test_every_agent_command_goes_through_docker_exec(monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"/workspace/a.py\n")

    monkeypatch.setattr(docker_env.subprocess, "run", fake_run)
    env = DockerEnv("img", "tests")
    tb = Toolbox(env, "python -m pytest tests")
    for name, args in [("bash", {"command": "rm -rf / --no-preserve-root"}), ("view_file", {"path": "a.py"}),
                       ("search", {"pattern": "x"}), ("str_replace", {"path": "a.py", "old_str": "/", "new_str": "y"}),
                       ("run_tests", {})]:
        tb.execute(ToolCall("1", name, args))
    assert calls, "no commands issued"
    for argv in calls:
        assert argv[:2] == ["docker", "exec"], argv
        assert env.name in argv


def test_unsafe_local_requires_flag_and_toy_repo(tmp_path):
    with pytest.raises(PermissionError):
        UnsafeLocalEnv(TOY_REPO)
    with pytest.raises(PermissionError):
        UnsafeLocalEnv(tmp_path, unsafe_local=True)


def test_secrets_redacted_in_trajectory(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value-123")
    t = Trajectory(tmp_path / "t.jsonl")
    t.log({"text": "my key is sk-ant-secret-value-123"})
    assert "sk-ant-secret" not in (tmp_path / "t.jsonl").read_text()
    assert redact("a sk-ant-secret-value-123 b", ["sk-ant-secret-value-123"]) == "a [REDACTED] b"
