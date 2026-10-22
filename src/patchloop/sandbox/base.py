"""The interface every sandbox implements. Tools only ever talk to an Env."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

WORKSPACE = "/workspace"


@dataclass
class ExecResult:
    exit_code: int
    output: str  # stdout and stderr, interleaved
    timed_out: bool = False


class SandboxError(RuntimeError):
    """Infrastructure failure (container would not start, docker missing, ...)."""


class Env(Protocol):
    tests_dir: str

    def exec(self, command: str, timeout_s: int = 60) -> ExecResult: ...

    def write_file(self, path: str, content: str) -> ExecResult: ...

    def read_file(self, path: str) -> tuple[str | None, str]: ...

    def diff(self) -> str: ...

    def close(self) -> None: ...
