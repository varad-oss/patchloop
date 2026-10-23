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
