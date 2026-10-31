# PatchLoop over MCP

`src/patchloop/mcp_server/server.py` serves `bash`, `view_file`, `search`, `str_replace`, `run_tests` (and a
read-only `diff`) over stdio with the official Python SDK (`mcp` 2.3.0, `MCPServer`). Each MCP session gets one
sandbox container, created on the first tool call, removed after `PATCHLOOP_MCP_IDLE_S` (default 600 s) idle
and on shutdown.

**Targets.**
- **Your own repository** (`--repo PATH` or `PATCHLOOP_MCP_REPO`), prepared once with `patchloop mcp-prepare PATH`.
  This builds `patchloop/user-<name>-<hash>` from `sandbox/images/Dockerfile.user` (the repo plus an editable install
  of its dependencies; network only at build time), detects the tests directory, and saves a config under
  `~/.cache/patchloop/mcp_repos/`. The model edits a copy inside the container; `diff` returns the patch.
  `Dockerfile.user.dockerignore` keeps `.git`, virtualenvs, caches and `.env` files out of the image.
- **A benchmark task** (`PATCHLOOP_MCP_TASK=bench/tasks/<id>.json`).
- **The demo** (the default): the toy repo with a planted `median()` bug.

Tested by `tests/integration/test_mcp_server.py` (SDK client, in-process, real Docker container: the demo, and a copy
of `toy_repo` prepared as a user's project) and `tests/unit/test_mcp_prepare.py` (detection, config, server wiring).

## Claude Code

```bash
patchloop mcp-prepare /ABSOLUTE/PATH/myproject
claude mcp add patchloop -- "/ABSOLUTE/PATH/patchloop/.venv/bin/patchloop-mcp" --repo /ABSOLUTE/PATH/myproject
```

Omit `--repo` for the demo. `mcp-prepare` prints the exact `claude mcp add` line for your paths.

## Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "patchloop": {
      "command": "/ABSOLUTE/PATH/patchloop/.venv/bin/patchloop-mcp",
      "args": ["--repo", "/ABSOLUTE/PATH/myproject"],
      "env": {"PATCHLOOP_MCP_IDLE_S": "600"}
    }
  }
}
```

## Limits

- Python projects with a pytest suite in a sub-directory (it is mounted read-only, so it cannot be the whole repo).
- The image is a snapshot: after you change the code yourself, re-run `mcp-prepare` (fast when dependencies are cached).
- Dependencies needing system packages beyond `python:3.12-slim` (plus git and ripgrep) fail at build time, with
  Docker's error shown.
- `run_tests` summarises pytest's final count line; projects whose own config already passes `-q` print no such line,
  so read the exit code instead.

## Risks and how this server limits them

| Risk | Mitigation here |
|---|---|
| **Tool poisoning** (instructions hidden in tool descriptions) | Descriptions are the same plain text the agent uses, in `agent/tools.py`; no hidden directives. Review them before installing any MCP server. |
| **Over-broad permissions** (a `bash` tool on your machine) | `bash` runs inside the locked-down container: no network, read-only root, non-root, no capabilities, CPU/memory/PID limits. It never touches the host. |
| **Data exfiltration** | `--network none`; no secrets are passed into the container. |
| **Prompt injection via tool output** (repo content telling the model to do things) | Contained by the sandbox: the worst case is edits to a throwaway workspace. Tests are read-only. |
| **Resource leaks** | One container per session, idle reaper, cleanup on shutdown and at interpreter exit. |

## Headless demo (reproducible)

Recorded result: [MCP_DEMO.md](MCP_DEMO.md). Write a config file `mcp.json` with the server (as for Claude Desktop
above), then run Claude Code with every built-in tool disabled, so it can only act through the sandbox:

```bash
claude -p "Use only the patchloop tools. A user reports that median() returns the wrong value for lists with an even number of elements. Run the tests, find the cause, fix it with str_replace, and run the tests again. Then, as a check of the sandbox, try once to change the expected value in tests/test_stats.py and report what happens. Finally call diff and summarise the root cause and your fix in two sentences." --strict-mcp-config --mcp-config mcp.json --tools "" --allowedTools "mcp__patchloop__*" --output-format stream-json --verbose --model haiku > transcript.jsonl
```

```bash
python scripts/render_mcp_demo.py transcript.jsonl
```

## Demo recording checklist

1. `make images` and confirm `make test-docker` passes.
2. Add the server to Claude Code (command above); start `claude` in an empty directory.
3. Prompt: *"Use the patchloop tools. Run the tests, find why median() is wrong for even-length lists, fix it
   with str_replace, run the tests again and show me the diff."*
4. Record: the failing `run_tests`, the `search`/`view_file` calls, the `str_replace`, the passing tests, `diff`.
5. Bonus shot: ask it to edit `tests/test_stats.py` and show the "Read-only file system" error.
6. Exit; run `docker ps --filter label=patchloop=1` to show the container is gone.
