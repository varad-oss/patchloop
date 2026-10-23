# PatchLoop

From-scratch coding agent that fixes failing tests in a Docker sandbox. Spec: `docs/project/SPEC.md`.
State: `docs/project/PROGRESS.md`. Decisions: `docs/DECISIONS.md`. Design: `docs/ARCHITECTURE.md`.

## Commands
- `make setup` / `make images` (Docker images for toy, toolz, boltons)
- `make test` (unit, no Docker) · `make test-docker` (integration + sandbox security) · `make lint`
- `make demo` (FakeModel fixes the toy bug, no API key) · `make bench` (36 tasks, no API calls)
- `make eval-smoke` (free) · `make eval-pilot RUN=E1` (3 paid tasks, prints cost) · `make eval RUN=E1` (after approval)
- `patchloop eval --model oracle --run-id oracle` must resolve 100% (harness sanity check)
- Free local model (Ollama, ADR-011): `make local-model`, `make eval-local RUN=E1 [TOOLSET=bash_only]`,
  `scripts/run_local_experiments.sh`, `scripts/run_strategy_b.sh`; `make progress` (live dashboard)
- `patchloop report --all` (regenerates docs/EVAL_REPORT.md) · `patchloop replay` (trajectory -> docs/demo.gif)

## Rules
- No agent frameworks in `src/patchloop/agent/`; `loop.py` stays <= 250 lines.
- Agent commands only via `DockerEnv` (`_run_docker` asserts it). `--unsafe-local` is toy_repo-only.
- Never weaken/delete tests; never special-case tasks. Numbers in docs come from `results/` only.
- Paid runs: pilot first, wait for the user's OK. Secrets only in `.env`.
- History is append-only (thinking blocks are replayed unchanged); compaction starts a fresh list.
