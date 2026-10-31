"""`patchloop mcp-prepare` and the MCP server's repo mode, without Docker."""

import subprocess

import anyio
import pytest
from mcp import Client

from patchloop.mcp_server import prepare as prep
from patchloop.mcp_server.server import build_server
from patchloop.sandbox.base import ExecResult


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PATCHLOOP_CACHE", str(tmp_path / "cache"))


def make_repo(root, *dirs):
    root.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        (root / d).mkdir(parents=True)
    return root


@pytest.mark.parametrize("dirs, expected", [
    (["tests"], "tests"), (["test"], "test"), (["mypkg/tests"], "mypkg/tests"), (["src/mypkg/tests"], "src/mypkg/tests"),
    (["tests", "mypkg/tests"], "tests"),
])
def test_detect_tests_dir(tmp_path, dirs, expected):
    assert prep.detect_tests_dir(make_repo(tmp_path / "r", *dirs)) == expected


def test_detect_tests_dir_missing(tmp_path):
    with pytest.raises(prep.PrepareError, match="--tests-dir"):
        prep.detect_tests_dir(make_repo(tmp_path / "r", "docs"))


@pytest.mark.parametrize("bad", ["", ".", "/", "../x", "/etc", "nope"])
def test_tests_dir_must_be_a_real_subdirectory(tmp_path, bad):
    with pytest.raises(prep.PrepareError):
        prep.check_tests_dir(make_repo(tmp_path / "r", "tests"), bad)


def test_key_is_stable_and_safe(tmp_path):
    a, b = make_repo(tmp_path / "My Repo!"), make_repo(tmp_path / "other" / "My Repo!")
    assert prep.repo_key(a) == prep.repo_key(a) and prep.repo_key(a) != prep.repo_key(b)
    assert prep.image_tag(a).startswith("patchloop/user-my-repo-") and " " not in prep.image_tag(a)


def test_prepare_builds_and_saves_config(tmp_path):
    repo, calls = make_repo(tmp_path / "proj", "tests"), []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    cfg = prep.prepare(repo, run=fake_run, log=lambda *_: None)
    assert calls == [prep.build_argv(repo.resolve(), cfg["image"])]
    assert calls[0][:2] == ["docker", "build"] and calls[0][-1] == str(repo.resolve())
    assert cfg["tests_dir"] == "tests" and cfg["bug_patch"] is None
    assert cfg["test_cmd"] == "python -m pytest -p no:cacheprovider tests"
    assert prep.load_config(repo) == cfg


def test_failed_build_saves_nothing(tmp_path):
    repo = make_repo(tmp_path / "proj", "tests")
    with pytest.raises(prep.PrepareError, match="docker build failed"):
        prep.prepare(repo, run=lambda argv, **kw: subprocess.CompletedProcess(argv, 1), log=lambda *_: None)
    with pytest.raises(prep.PrepareError, match="mcp-prepare"):
        prep.load_config(repo)


def test_dockerignore_keeps_secrets_and_history_out():
    ignored = (prep.DOCKERFILE.parent / "Dockerfile.user.dockerignore").read_text().split()
    assert {".git", "**/.env", "**/.env.*", "**/.venv"} <= set(ignored)


class FakeEnv:
    def __init__(self, image, tests_dir, bug_patch):
        self.args, self.closed = (image, tests_dir, bug_patch), False

    def start(self):
        return self

    def exec(self, command, timeout_s=60):
        return ExecResult(0, "1 passed in 0.01s")

    def diff(self):
        return "diff --git a/m.py b/m.py\n"

    def close(self):
        self.closed = True


def test_server_serves_a_prepared_repo(tmp_path):
    repo = make_repo(tmp_path / "proj", "tests")
    cfg = prep.prepare(repo, run=lambda argv, **kw: subprocess.CompletedProcess(argv, 0), log=lambda *_: None)
    server = build_server(repo=repo, env_factory=FakeEnv, idle_s=600)

    async def scenario():
        async with Client(server) as client:
            assert "proj" in client.instructions
            assert "git apply" in client.instructions
            tests = await client.call_tool("run_tests", {})
            diff = await client.call_tool("diff", {})
            return tests.content[0].text, diff.content[0].text

    try:
        tests, diff = anyio.run(scenario)
    finally:
        server.session.shutdown()
    assert "1 passed" in tests and diff.startswith("diff --git")
    assert server.session.task["image"] == cfg["image"]


def test_server_refuses_an_unprepared_repo(tmp_path):
    with pytest.raises(prep.PrepareError, match="mcp-prepare"):
        build_server(repo=make_repo(tmp_path / "proj", "tests"), env_factory=FakeEnv)
