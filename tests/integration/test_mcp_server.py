"""MCP server end-to-end with the SDK's own client, in-process, against toy_repo in Docker."""

import anyio
import pytest
from mcp import Client

from patchloop.mcp_server.server import build_server

pytestmark = pytest.mark.docker


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def test_mcp_client_fixes_toy_bug():
    server = build_server(idle_s=600)

    async def scenario():
        async with Client(server) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            assert {"bash", "view_file", "search", "str_replace", "run_tests", "diff"} <= tools
            before = _text(await client.call_tool("run_tests", {}))
            assert "1 failed" in before
            edit = _text(await client.call_tool("str_replace", {
                "path": "toyrepo/stats.py", "old_str": "(ordered[mid] + ordered[mid + 1])",
                "new_str": "(ordered[mid - 1] + ordered[mid])"}))
            assert edit.startswith("Edited")
            blocked = _text(await client.call_tool("bash", {"command": "echo x >> tests/test_stats.py"}))
            assert "Read-only file system" in blocked
            after = _text(await client.call_tool("run_tests", {}))
            assert "6 passed" in after
            assert "ordered[mid - 1]" in _text(await client.call_tool("diff", {}))

    try:
        anyio.run(scenario)
    finally:
        server.session.shutdown()
    assert server.session.env is None


def test_mcp_on_your_own_repo(tmp_path, monkeypatch):
    """A copy of toy_repo stands in for a user's project: prepare it, fix it through MCP, host files untouched."""
    import shutil
    import subprocess
    from pathlib import Path

    from patchloop.mcp_server.prepare import prepare

    monkeypatch.setenv("PATCHLOOP_CACHE", str(tmp_path / "cache"))
    repo = tmp_path / "myproject"
    shutil.copytree(Path(__file__).parents[2] / "toy_repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
    stats = repo / "toyrepo" / "stats.py"
    stats.write_text(stats.read_text().replace("(ordered[mid - 1] + ordered[mid])", "(ordered[mid] + ordered[mid + 1])"))
    (repo / ".env").write_text("API_KEY=do-not-copy-me\n")
    original = stats.read_text()

    cfg = prepare(repo, log=lambda *_: None)
    server = build_server(repo=repo, idle_s=600)

    async def scenario():
        async with Client(server) as client:
            assert "1 failed" in _text(await client.call_tool("run_tests", {}))
            assert "No such file" in _text(await client.call_tool("bash", {"command": "cat .env"}))
            assert "Read-only file system" in _text(await client.call_tool(
                "bash", {"command": "echo x >> tests/test_stats.py"}))
            edit = _text(await client.call_tool("str_replace", {
                "path": "toyrepo/stats.py", "old_str": "(ordered[mid] + ordered[mid + 1])",
                "new_str": "(ordered[mid - 1] + ordered[mid])"}))
            assert edit.startswith("Edited")
            assert "6 passed" in _text(await client.call_tool("run_tests", {}))
            return _text(await client.call_tool("diff", {}))

    try:
        patch = anyio.run(scenario)
    finally:
        server.session.shutdown()
        subprocess.run(["docker", "image", "rm", "-f", cfg["image"]], capture_output=True, check=False)
    assert "+    return (ordered[mid - 1] + ordered[mid]) / 2" in patch
    assert stats.read_text() == original  # the agent edited a copy; the user's file is unchanged
    applied = subprocess.run(["git", "apply", "--check", "-"], input=patch.encode(), cwd=repo, capture_output=True)
    assert applied.returncode == 0, applied.stderr  # and the returned patch applies to the user's checkout
