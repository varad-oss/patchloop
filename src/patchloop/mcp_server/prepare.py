"""Prepare a user's own Python repository for the MCP server: `patchloop mcp-prepare <repo>`.

Builds one image with the repository and its dependencies (network is used only at build time, as for the
benchmark images), detects the tests directory, and saves a small config that the server loads in place of a
task file. The agent works on a copy inside the container: the repository on the host is never written to.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from ..sandbox.docker_env import cache_root, snapshot_dir

DOCKERFILE = Path(__file__).resolve().parents[1] / "sandbox" / "images" / "Dockerfile.user"
TESTS_DIR_CANDIDATES = ("tests", "test")


class PrepareError(RuntimeError):
    pass


def repo_key(repo: Path) -> str:
    """Stable per checkout: the folder name (for humans) plus a hash of its absolute path (for uniqueness)."""
    repo = Path(repo).expanduser().resolve()
    name = re.sub(r"[^a-z0-9_.-]+", "-", repo.name.lower()).strip("-.") or "repo"
    return f"{name[:40]}-{hashlib.sha256(str(repo).encode()).hexdigest()[:8]}"


def image_tag(repo: Path) -> str:
    return f"patchloop/user-{repo_key(repo)}:latest"


def config_path(repo: Path) -> Path:
    return cache_root() / "mcp_repos" / f"{repo_key(repo)}.json"


def detect_tests_dir(repo: Path) -> str:
    for name in TESTS_DIR_CANDIDATES:
        if (repo / name).is_dir():
            return name
    nested = sorted(p.relative_to(repo).as_posix() for pattern in ("*/tests", "src/*/tests")
                    for p in repo.glob(pattern) if p.is_dir())
    if nested:
        return nested[0]
    raise PrepareError(f"no tests directory found in {repo} (looked for tests/, test/, <package>/tests); "
                       "pass --tests-dir")


def check_tests_dir(repo: Path, tests_dir: str) -> str:
    tests_dir = tests_dir.strip().strip("/")
    if tests_dir in ("", ".") or ".." in Path(tests_dir).parts or Path(tests_dir).is_absolute():
        raise PrepareError(f"--tests-dir must be a sub-directory of the repository, got {tests_dir!r} "
                           "(it is mounted read-only, so it cannot be the whole repository)")
    if not (repo / tests_dir).is_dir():
        raise PrepareError(f"{repo / tests_dir} is not a directory")
    return tests_dir


def build_argv(repo: Path, tag: str) -> list[str]:
    return ["docker", "build", "-t", tag, "--label", "patchloop=1", "-f", str(DOCKERFILE), str(repo)]


def prepare(repo: Path, tests_dir: str | None = None, test_cmd: str | None = None,
            run: Callable[..., subprocess.CompletedProcess] = subprocess.run, log=print) -> dict:
    repo = Path(repo).expanduser().resolve()
    if not repo.is_dir():
        raise PrepareError(f"{repo} is not a directory")
    tests_dir = check_tests_dir(repo, tests_dir if tests_dir is not None else detect_tests_dir(repo))
    test_cmd = test_cmd or f"python -m pytest -p no:cacheprovider {tests_dir}"
    tag = image_tag(repo)
    log(f"building {tag} from {repo} (tests: {tests_dir}/) ...")
    if run(build_argv(repo, tag), check=False).returncode != 0:
        raise PrepareError("docker build failed (see the output above). Common causes: Docker is not running, "
                           "or a dependency needs system libraries that python:3.12-slim does not have.")
    shutil.rmtree(snapshot_dir(tag, tests_dir), ignore_errors=True)  # the tests may have changed since last time
    cfg = {"repo": str(repo), "name": repo.name, "image": tag, "tests_dir": tests_dir, "test_cmd": test_cmd,
           "bug_patch": None, "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    path = config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2))
    log(f"ready: {path}")
    return cfg


def load_config(repo: Path) -> dict:
    path = config_path(repo)
    if not path.exists():
        raise PrepareError(f"{Path(repo).expanduser().resolve()} is not prepared yet. "
                           f"Run: patchloop mcp-prepare {repo}")
    return json.loads(path.read_text())
