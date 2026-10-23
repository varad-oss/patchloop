"""PatchLoop's tools over MCP (official Python SDK v2, `mcp.server.mcpserver.MCPServer`).

One sandbox container per MCP session (a stdio server process serves one session). It is created
lazily on the first tool call, destroyed after PATCHLOOP_MCP_IDLE_S seconds without a call, and
on shutdown. Same isolation as episodes: no network, read-only tests, non-root, no capabilities.

The tool descriptions are the same plain descriptions the agent gets; they contain no hidden
instructions. Configure the target with env vars:
  PATCHLOOP_MCP_TASK   path to a task JSON (default: bench/toy/toy__median-even.json)
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from mcp.server.mcpserver import MCPServer

from ..agent.models import ToolCall
from ..agent.tools import TOOL_SPECS, Toolbox
from ..config import ROOT
from ..sandbox.docker_env import DockerEnv

DEFAULT_TASK = ROOT / "bench" / "toy" / "toy__median-even.json"


class SandboxSession:
    def __init__(self, task_path: Path, idle_s: float, env_factory=DockerEnv):
        self.task = json.loads(Path(task_path).read_text())
        self.idle_s = idle_s
        self.env_factory = env_factory
        self.env = None
        self.toolbox: Toolbox | None = None
        self.last_used = time.monotonic()
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap, daemon=True)
        self._reaper.start()

    def _ensure(self) -> Toolbox:
        if self.env is None:
            t = self.task
            self.env = self.env_factory(t["image"], t["tests_dir"], t["bug_patch"]).start()
            self.toolbox = Toolbox(self.env, t["test_cmd"], "structured")
        return self.toolbox

    def call(self, name: str, args: dict) -> str:
        with self.lock:
            self.last_used = time.monotonic()
            obs = self._ensure().execute(ToolCall(f"mcp_{time.time_ns()}", name, args))
            self.last_used = time.monotonic()
        return ("ERROR: " if obs.is_error else "") + obs.content

    def _reap(self) -> None:
        while not self._stop.wait(5):
            with self.lock:
                if self.env is not None and time.monotonic() - self.last_used > self.idle_s:
                    self.close_env()

    def close_env(self) -> None:
        if self.env is not None:
            self.env.close()
            self.env, self.toolbox = None, None

    def shutdown(self) -> None:
        self._stop.set()
        with self.lock:
            self.close_env()


def build_server(task_path: Path | None = None, idle_s: float | None = None, env_factory=DockerEnv) -> MCPServer:
    session = SandboxSession(
        Path(task_path or os.environ.get("PATCHLOOP_MCP_TASK", DEFAULT_TASK)),
        float(idle_s if idle_s is not None else os.environ.get("PATCHLOOP_MCP_IDLE_S", 600)),
        env_factory,
    )

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield {}
        finally:
            await anyio.to_thread.run_sync(session.shutdown)

    server = MCPServer(
        "patchloop",
        instructions=(f"Tools operate on one Python repository in an isolated Docker sandbox (no network, tests "
                      f"read-only). Issue: {session.task['problem_statement']}"),
        lifespan=lifespan,
    )

    async def run(name: str, **args) -> str:
        return await anyio.to_thread.run_sync(session.call, name, {k: v for k, v in args.items() if v is not None})

    @server.tool(description=TOOL_SPECS["bash"].description)
    async def bash(command: str, timeout_s: int = 60) -> str:
        return await run("bash", command=command, timeout_s=timeout_s)

    @server.tool(description=TOOL_SPECS["view_file"].description)
    async def view_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        return await run("view_file", path=path, start_line=start_line, end_line=end_line)

    @server.tool(description=TOOL_SPECS["search"].description)
    async def search(pattern: str, path: str = ".", glob: str | None = None) -> str:
        return await run("search", pattern=pattern, path=path, glob=glob)

    @server.tool(description=TOOL_SPECS["str_replace"].description)
    async def str_replace(path: str, old_str: str, new_str: str) -> str:
        return await run("str_replace", path=path, old_str=old_str, new_str=new_str)

    @server.tool(description=TOOL_SPECS["run_tests"].description)
    async def run_tests(selector: str | None = None) -> str:
        return await run("run_tests", selector=selector)

    @server.tool(description="Show the current git diff of the sandboxed repository (your changes so far).")
    async def diff() -> str:
        return await anyio.to_thread.run_sync(lambda: session._ensure() and session.env.diff() or "(no changes)")

    server.session = session  # for tests
    return server


def main() -> None:
    build_server().run()  # stdio


if __name__ == "__main__":
    main()
