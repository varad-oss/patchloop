# PatchLoop

From-scratch coding agent that fixes failing tests in a Docker sandbox. Spec: `docs/SPEC.md`.
State: `docs/PROGRESS.md`. Decisions: `docs/DECISIONS.md`. Design: `docs/ARCHITECTURE.md`.

## Commands
- `make setup` / `make images` (Docker images for toy, toolz, boltons)
- `make test` (unit, no Docker) · `make test-docker` (integration + sandbox security) · `make lint`
- `make demo` (FakeModel fixes the toy bug, no API key) · `make bench` (36 tasks, no API calls)
- `make eval-smoke` (free) · `make eval-pilot RUN=E1` (3 paid tasks, prints cost) · `make eval RUN=E1` (after approval)
- `patchloop eval --model oracle --run-id oracle` must resolve 100% (harness sanity check)

## Rules
- No agent frameworks in `src/patchloop/agent/`; `loop.py` stays <= 250 lines.
- Agent commands only via `DockerEnv` (`_run_docker` asserts it). `--unsafe-local` is toy_repo-only.
- Never weaken/delete tests; never special-case tasks. Numbers in docs come from `results/` only.
- Paid runs: pilot first, wait for the user's OK. Secrets only in `.env`.
- History is append-only (thinking blocks are replayed unchanged); compaction starts a fresh list.
