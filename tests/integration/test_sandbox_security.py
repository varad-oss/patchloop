"""The sandbox boundary, tested against a real container."""

import json
import uuid
from pathlib import Path

import pytest

from patchloop.agent.models import ToolCall
from patchloop.agent.tools import Toolbox
from patchloop.sandbox.docker_env import DockerEnv

pytestmark = pytest.mark.docker
TASK = json.loads((Path(__file__).parents[2] / "bench" / "toy" / "toy__median-even.json").read_text())


@pytest.fixture(scope="module")
def env():
    with DockerEnv(TASK["image"], TASK["tests_dir"], TASK["bug_patch"]) as e:
        yield e


def test_no_network(env):
    r = env.exec("python -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\"", 20)
    assert r.exit_code != 0 and "unreachable" in r.output.lower()
    assert "lo" in env.exec("ls /sys/class/net").output and "eth0" not in env.exec("ls /sys/class/net").output


def test_tests_are_read_only(env):
    r = env.exec("echo 'def test_x(): pass' >> tests/test_stats.py", 10)
    assert r.exit_code != 0 and "Read-only file system" in r.output
    assert env.exec("rm tests/test_stats.py", 10).exit_code != 0
    obs = Toolbox(env, TASK["test_cmd"]).execute(
        ToolCall("1", "str_replace", {"path": "tests/test_stats.py", "old_str": "median([4, 1, 3, 2]) == 2.5", "new_str": "median([4, 1, 3, 2]) == 3.5"}))
    assert obs.is_error and "Read-only" in obs.content


def test_root_filesystem_read_only_and_non_root(env):
    assert "Read-only file system" in env.exec("touch /etc/pwned", 10).output
    assert env.exec("id -u", 10).output.strip() == "1000"
    assert env.exec("touch /tmp/ok && touch /workspace/ok && rm /workspace/ok", 10).exit_code == 0


def test_no_privilege_escalation(env):
    status = env.exec("grep -E 'CapEff|NoNewPrivs' /proc/self/status", 10).output
    assert "CapEff:\t0000000000000000" in status and "NoNewPrivs:\t1" in status


def test_memory_limit_enforced(env):
    r = env.exec("python -c \"x = bytearray(1500 * 1024 * 1024); print('allocated')\"", 60)
    assert "allocated" not in r.output and r.exit_code != 0


def test_pid_limit_enforced():
    # Own container: the forked sleepers would starve the shared one.
    with DockerEnv(TASK["image"], TASK["tests_dir"]) as env:
        r = env.exec("python -c \"import os,time\nfor i in range(400):\n    pid=os.fork()\n    "
                 "if pid==0: time.sleep(5); os._exit(0)\nprint('forked all')\"", 60)
        assert "forked all" not in r.output
        assert "Resource temporarily unavailable" in r.output or "BlockingIOError" in r.output


def test_command_timeout(env):
    r = env.exec("sleep 30", 2)
    assert r.timed_out


def test_cannot_touch_host(env, tmp_path):
    marker = tmp_path / f"host-{uuid.uuid4().hex}"
    env.exec(f"touch {marker}; echo hi > {marker}", 10)
    assert not marker.exists()
    assert env.exec(f"ls {Path.home()}", 10).exit_code != 0


def test_git_history_does_not_leak_the_bug(env):
    log = env.exec("git log --oneline | wc -l", 10).output.strip()
    assert log == "1"
    assert env.exec("git diff HEAD", 10).output.strip() == ""


def test_tests_hash_stable(env):
    assert env.tests_hash() == env.tests_hash()


def test_container_removed_on_close():
    e = DockerEnv(TASK["image"], TASK["tests_dir"]).start()
    name = e.name
    e.close()
    import subprocess

    out = subprocess.run(["docker", "ps", "-a", "--filter", f"name={name}", "-q"], capture_output=True, text=True)
    assert out.stdout.strip() == ""
