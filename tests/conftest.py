import shutil
import subprocess

import pytest

from patchloop.sandbox.base import ExecResult


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "image", "inspect", "patchloop/toy:latest"], capture_output=True)
    return r.returncode == 0


def pytest_collection_modifyitems(config, items):
    if _docker_ready():
        return
    skip = pytest.mark.skip(reason="Docker or patchloop images unavailable (run `make images`)")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)


class MemEnv:
    """In-memory Env for unit tests: a dict filesystem; exec only understands `readlink -m`."""

    tests_dir = "tests"

    def __init__(self, files=None, readonly=("/workspace/tests/",)):
        self.files = dict(files or {})
        self.readonly = readonly
        self.commands = []

    def exec(self, command, timeout_s=60):
        self.commands.append(command)
        if command.startswith("readlink -m -- "):
            return ExecResult(0, command.split("-- ", 1)[1].strip("'") + "\n")
        return ExecResult(0, f"ran: {command}")

    def write_file(self, path, content):
        if any(path.startswith(r) for r in self.readonly):
            return ExecResult(1, f"bash: {path}: Read-only file system")
        self.files[path] = content
        return ExecResult(0, "")

    def read_file(self, path):
        if path not in self.files:
            return None, f"cat: {path}: No such file or directory"
        return self.files[path], ""

    def diff(self):
        return ""

    def close(self):
        pass


@pytest.fixture
def mem_env():
    return MemEnv({"/workspace/pkg/mod.py": "def f(x):\n    a = 1\n    b = 1\n    return x + 1\n",
                   "/workspace/tests/test_mod.py": "def test_f():\n    assert True\n"})
