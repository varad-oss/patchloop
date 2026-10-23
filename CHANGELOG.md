# Changelog

## v0.1.0 — 2026-10-24

First public release.

- Agent loop written from scratch (`agent/loop.py`, 209 lines): step, cost and wall-time budgets, retries with
  backoff and jitter, loop detection, append-only history, compaction into a fresh context, JSONL trajectories.
- Model adapters: Anthropic (Claude Haiku 5.5 request surface), OpenAI-compatible, local Ollama, and a scripted fake.
- Six-tool agent-computer interface (`bash`, `view_file`, `search`, `str_replace`, `run_tests`, `submit`) plus a
  bash-only toolset for ablation.
- Locked-down Docker sandbox per episode, with security tests.
- Benchmark generator: 36 validated syntax-tree-mutation tasks on toolz and boltons, leak-checked bug reports;
  LLM-rewrite generator (6 extra tasks, not yet evaluated).
- Evaluation: parallel resumable runner, grader in a fresh container, Wilson intervals, pass@k / pass^k, exact
  McNemar test, failure classification, HTML trajectory viewer, GIF replay, live progress dashboard.
- Results on local `qwen3:8b` (free): structured toolset 12/36 (33.3%) vs bash only 3/36 (8.3%), McNemar p = 0.022.
- MCP server exposing the sandboxed tools (official Python SDK v2).
