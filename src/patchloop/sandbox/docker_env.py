"""One locked-down Docker container per episode.

Every agent-issued command goes through `docker exec` into this container. Nothing the agent
writes is ever executed on the host: `_run_docker` refuses any argv that is not a docker
subcommand from a fixed allow-list (tested in tests/unit/test_sandbox_unit.py).

Isolation (verified flag names, Docker 29.7 `docker run --help`):
  --network none                 no network at all
  --memory 1g --memory-swap 1g   1 GB RAM, no extra swap
  --cpus 1                       one CPU
  --pids-limit 256               fork bombs hit a wall
  --read-only + --tmpfs /tmp     immutable root filesystem, scratch space in RAM
  anonymous volume at /workspace writable copy of the repo, deleted with the container (--rm)
  tests bind-mounted :ro         edits to tests fail with "Read-only file system"
  --user 1000:1000               non-root
  --security-opt no-new-privileges, --cap-drop ALL
  timeout -k 2 <s> per command   per-command wall clock limit, inside the container
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shlex
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from .base import WORKSPACE, ExecResult, SandboxError

ALLOWED_DOCKER_SUBCOMMANDS = {"run", "exec", "rm", "create", "cp", "image", "ps", "inspect"}
GIT = "git -c user.name=patchloop -c user.email=patchloop@localhost -c init.defaultBranch=main"
_LIVE: set[str] = set()
_LIVE_LOCK = threading.Lock()


def _run_docker(argv: list[str], *, input_bytes: bytes | None = None, timeout: float = 120) -> subprocess.CompletedProcess:
    """The only place this module starts a process. It must be a docker CLI call."""
    assert argv[0] == "docker" and argv[1] in ALLOWED_DOCKER_SUBCOMMANDS, f"refusing host command: {argv[:2]}"
    return subprocess.run(argv, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout, check=False,
                          stdin=None if input_bytes is not None else subprocess.DEVNULL)


def _cleanup_all() -> None:
    with _LIVE_LOCK:
        names = list(_LIVE)
    for name in names:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


atexit.register(_cleanup_all)


def tests_snapshot(image: str, tests_dir: str) -> Path:
    """Copy the image's tests directory to the host once; it is bind-mounted read-only."""
    root = Path(os.environ.get("PATCHLOOP_CACHE", Path.home() / ".cache" / "patchloop")) / "tests"
    target = root / image.replace("/", "_").replace(":", "_") / tests_dir.replace("/", "_")
    if (target / ".complete").exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=target.parent))
    cid = _run_docker(["docker", "create", image]).stdout.decode().strip()
    try:
        res = _run_docker(["docker", "cp", f"{cid}:{WORKSPACE}/{tests_dir}/.", str(tmp)])
        if res.returncode != 0:
            raise SandboxError(f"docker cp failed: {res.stdout.decode()[-500:]}")
    finally:
        _run_docker(["docker", "rm", "-f", cid])
    (tmp / ".complete").write_text("ok")
    if target.exists():  # another worker won the race
        return target
    tmp.rename(target)
    return target


class DockerEnv:
    def __init__(self, image: str, tests_dir: str, bug_patch: str | None = None, *,
                 memory: str = "1g", cpus: str = "1", pids: int = 256):
        self.image = image
        self.tests_dir = tests_dir.strip("/")
        self.bug_patch = bug_patch
        self.limits = (memory, cpus, pids)
        self.name = f"patchloop-{uuid.uuid4().hex[:12]}"
        self.started = False

    # -------------------------------------------------------------- lifecycle

    def run_argv(self, tests_host_dir: Path) -> list[str]:
        memory, cpus, pids = self.limits
        return [
            "docker", "run", "-d", "--rm", "--name", self.name,
            "--label", "patchloop=1",
            "--network", "none",
            "--memory", memory, "--memory-swap", memory,
            "--cpus", cpus,
            "--pids-limit", str(pids),
            "--read-only",
            "--tmpfs", "/tmp:rw,exec,size=256m,mode=1777",
            "--mount", f"type=volume,dst={WORKSPACE}",
            "--mount", f"type=bind,src={tests_host_dir},dst={WORKSPACE}/{self.tests_dir},readonly",
            "--user", "1000:1000",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--workdir", WORKSPACE,
            self.image, "sleep", "infinity",
        ]

    def start(self) -> DockerEnv:
        tests_host = tests_snapshot(self.image, self.tests_dir)
        with _LIVE_LOCK:
            _LIVE.add(self.name)
        res = _run_docker(self.run_argv(tests_host))
        if res.returncode != 0:
            self.close()
            raise SandboxError(f"docker run failed: {res.stdout.decode()[-800:]}")
        self.started = True
        if self.bug_patch:
            r = self.write_file("/tmp/bug.patch", self.bug_patch)
            r = self.exec("git apply /tmp/bug.patch && rm /tmp/bug.patch", 60) if r.exit_code == 0 else r
            if r.exit_code != 0:
                self.close()
                raise SandboxError(f"bug patch did not apply: {r.output[-800:]}")
        # Fresh history: the agent must not be able to `git diff HEAD~1` its way to the answer.
        r = self.exec(f"rm -rf .git && {GIT} init -q && {GIT} add -A && {GIT} commit -qm base", 60)
        if r.exit_code != 0:
            self.close()
            raise SandboxError(f"git reset failed: {r.output[-800:]}")
        return self

    def close(self) -> None:
        _run_docker(["docker", "rm", "-f", self.name], timeout=60)
        with _LIVE_LOCK:
            _LIVE.discard(self.name)
        self.started = False

    def __enter__(self) -> DockerEnv:
        return self.start()

    def __exit__(self, *exc) -> None:  # runs on KeyboardInterrupt too
        self.close()

    # -------------------------------------------------------------- operations

    def exec(self, command: str, timeout_s: int = 60) -> ExecResult:
        argv = ["docker", "exec", "--workdir", WORKSPACE, self.name,
                "timeout", "-k", "2", str(int(timeout_s)), "bash", "-c", command]
        try:
            res = _run_docker(argv, timeout=timeout_s + 15)
        except subprocess.TimeoutExpired:
            return ExecResult(124, f"[command timed out after {timeout_s}s]", True)
        out = res.stdout.decode("utf-8", errors="replace")
        timed_out = res.returncode in (124, 137)
        if timed_out:
            out += f"\n[command timed out after {timeout_s}s or was killed]"
        return ExecResult(res.returncode, out, timed_out)

    def write_file(self, path: str, content: str) -> ExecResult:
        argv = ["docker", "exec", "-i", "--workdir", WORKSPACE, self.name,
                "bash", "-c", f"cat > {shlex.quote(path)}"]
        res = _run_docker(argv, input_bytes=content.encode(), timeout=60)
        return ExecResult(res.returncode, res.stdout.decode("utf-8", errors="replace"))

    def read_file(self, path: str) -> tuple[str | None, str]:
        argv = ["docker", "exec", "--workdir", WORKSPACE, self.name, "cat", "--", path]
        res = _run_docker(argv, timeout=60)
        if res.returncode != 0:
            return None, res.stdout.decode("utf-8", errors="replace").strip()
        return res.stdout.decode("utf-8", errors="replace"), ""

    def diff(self) -> str:
        r = self.exec(f"{GIT} add -A >/dev/null && {GIT} diff --cached --binary", 60)
        return r.output if r.exit_code == 0 else ""

    def tests_hash(self) -> str:
        """Hash of every file under the tests directory, as seen inside the container."""
        r = self.exec(f"cd {shlex.quote(self.tests_dir)} && find . -type f -not -name '*.pyc' "
                      "-not -path '*/__pycache__/*' -print0 | sort -z | xargs -0 sha256sum", 60)
        return hashlib.sha256(r.output.encode()).hexdigest()
