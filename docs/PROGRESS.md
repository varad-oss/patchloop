# Progress (2026-10-23, build paused at usage limit)

Done (written, not yet tested):
- Scaffold: pyproject (pinned anthropic 2.1.0, openai 3.37.0, mcp 2.3.0), config/repos.toml (toolz + boltons, measured test times), config/pricing.toml
- seed/my_loop.py (stand-in written by Claude; Day-1 seed was missing)
- agent/: models.py (Anthropic/OpenAI-compatible/Fake adapters, pricing), tools.py (6 tools, truncation, traversal checks), prompts.py, context.py (compaction to a fresh list), trajectory.py, loop.py (201 lines)
- sandbox/: docker_env.py (all isolation flags), local_env.py (--unsafe-local, toy only), Dockerfiles
- bench/toy/toy__median-even.json

Next:
1. Fix the smoke test: `docker create patchloop/toy:latest` says the image is missing; check `docker images` and rebuild the images.
2. Unit + security tests, then M3 benchgen (mutators, validate, issues), M4 evals (runner, grader, metrics, report, viewer), M6 MCP server (mcp.server.mcpserver.MCPServer), M7 docs + learning notes, CLI, Makefile, CLAUDE.md, ADRs.
