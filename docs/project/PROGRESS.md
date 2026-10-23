# Progress

## 2026-10-24: v0.1.0 published

- Strategy B generated with the local model: 6 clean toolz tasks in `bench/tasks_llm/` (oracle 6/6), 3 malformed
  boltons tasks set aside after finding and fixing a re-indentation bug (ADR-013). Not evaluated (no E1b run).
- `patchloop replay` renders trajectories as GIFs (`docs/demo.gif`); `docs/project/BUG_REPORT_REVIEW.md` is the
  manual review sheet.
- Repo made presentable (README, LICENSE, CONTRIBUTING, SECURITY, CHANGELOG, uv-based CI) and pushed to GitHub.

## 2026-10-24: experiments done (free, local)

- **E1** (structured): 12/36 = 33.3% (95% CI 20.2-49.7%). **E2** (bash only): 3/36 = 8.3% (2.9-21.8%).
  Paired: 11 vs 2 discordant tasks, exact McNemar p = 0.022. Report: `docs/EVAL_REPORT.md`; analysis with three
  annotated failures: `docs/EVAL_ANALYSIS.md`.
- Model: `qwen3:8b` via Ollama (16K context, thinking off), $0. See ADR-011.
- Thinking on: 0/5 resolved, all at the 15-minute limit (`results/effort-low-r3`). Thinking off was chosen for E1/E2.
- Runs used `scripts/run_local_experiments.sh` with the GPU to itself. An earlier attempt sharing the GPU with
  another project's eval is kept separately in `results/effort-low-r2-shared-gpu` and is not used.
- Added during experiments: the Ollama route; a 20K-char observation cap; `str_replace` closest-region hint
  (ADR-012, disclosed); `make progress` dashboard; paired McNemar test and behavioural diagnostics in the report.

## 2026-10-23: build complete

- `make test` and `make test-docker` green (sandbox security, end-to-end, MCP). Ruff clean.
- `make bench`: 36 validated tasks (toolz 18, boltons 18), 0 leak-check rejections.
- Oracle run: 36/36 resolved (harness sanity check). `make eval-smoke`: the give-up model resolves 0/3.

Bugs found and fixed during the build:
- The toy image failed on git's "dubious ownership" check (`COPY --chown` followed by git running as root).
- In the PID-limit test, forked children starved a shared container. That test now gets its own container, and `--init` was added.
- The failure classifier read the trajectory's `end` record as a step.
- The leak-check regex missed "line 17" (the space between "line" and the number).

## Remaining (Varad, by hand)

1. Review the 10 bug reports in `docs/project/BUG_REPORT_REVIEW.md` (tick the boxes; ~15 min).
2. Study `docs/learning/` (start with `LOOP_WALKTHROUGH.md`, then M0-M7).
3. Replace `seed/my_loop.py` with your own loop, then rewrite the core loop from memory in 30 minutes.
4. Optional: record an MCP demo with Claude Code (`docs/MCP.md` checklist).
5. Optional, free, when the GPU is free: evaluate the strategy-B tasks (E1b).
