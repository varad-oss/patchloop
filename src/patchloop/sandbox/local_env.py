"""UNSAFE local environment: runs commands on the host in a temp copy of toy_repo/.

Exists only so the loop could be developed before the sandbox (M1). It refuses to start unless
the caller passes unsafe_local=True AND the source is the repository's own toy_repo/ directory.
Never used by the evaluation runner, the benchmark generator or the MCP server.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import WORKSPACE, ExecResult

TOY_REPO = (Path(__file__).resolve().parents[3] / "toy_repo").resolve()


class UnsafeLocalEnv:
    def __init__(self, source: Path, tests_dir: str = "tests", bug_patch: str | None = None, *,
                 unsafe_local: bool = False):
        if not unsafe_local:
            raise PermissionError("UnsafeLocalEnv requires the explicit --unsafe-local flag")
        if Path(source).resolve() != TOY_REPO:
            raise PermissionError(f"--unsafe-local is only allowed with {TOY_REPO}")
        self.source = Path(source)
        self.tests_dir = tests_dir
        self.bug_patch = bug_patch
        self.root: Path | None = None

    def start(self) -> UnsafeLocalEnv:
        self.root = Path(tempfile.mkdtemp(prefix="patchloop-unsafe-"))
        shutil.copytree(self.source, self.root, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        git = "git -c user.name=p -c user.email=p@localhost -c init.defaultBranch=main"
        if self.bug_patch:
            (self.root / "bug.patch").write_text(self.bug_patch)
            self.exec(f"{git} apply bug.patch && rm bug.patch")
        self.exec(f"{git} init -q && {git} add -A && {git} commit -qm base")
        return self

    def _host(self, path: str) -> Path:
        assert self.root is not None
        p = Path(path)
        if str(p).startswith(WORKSPACE):
            p = self.root / Path(path).relative_to(WORKSPACE)
        elif not p.is_absolute():
            p = self.root / p
        return p

    def exec(self, command: str, timeout_s: int = 60) -> ExecResult:
        assert self.root is not None
        command = command.replace(WORKSPACE, str(self.root))
        try:
            res = subprocess.run(["bash", "-c", command], cwd=self.root, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=timeout_s, env={
                                     "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                                     "PYTHONPATH": str(self.root), "PYTHONDONTWRITEBYTECODE": "1",
                                     "HOME": str(self.root)})
        except subprocess.TimeoutExpired:
            return ExecResult(124, f"[command timed out after {timeout_s}s]", True)
        out = res.stdout.decode("utf-8", errors="replace").replace(str(self.root), WORKSPACE)
        return ExecResult(res.returncode, out)

    def write_file(self, path: str, content: str) -> ExecResult:
        try:
            self._host(path).write_text(content)
            return ExecResult(0, "")
        except OSError as e:
            return ExecResult(1, str(e))

    def read_file(self, path: str) -> tuple[str | None, str]:
        try:
            return self._host(path).read_text(), ""
        except OSError as e:
            return None, str(e)

    def diff(self) -> str:
        git = "git -c user.name=p -c user.email=p@localhost"
        return self.exec(f"{git} add -A >/dev/null && {git} diff --cached --binary").output

    def tests_hash(self) -> str:
        assert self.root is not None
        h = hashlib.sha256()
        for f in sorted((self.root / self.tests_dir).rglob("*.py")):
            h.update(f.read_bytes())
        return h.hexdigest()

    def close(self) -> None:
        if self.root:
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> UnsafeLocalEnv:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()
