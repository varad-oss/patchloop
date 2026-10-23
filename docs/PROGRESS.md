# Progress

## 2026-10-23: build complete except paid experiments

- `make test`: 77 unit tests pass. `make test-docker`: 16 Docker tests pass (sandbox security, end-to-end, MCP). Ruff is clean.
- `make bench`: 36 validated tasks in `bench/tasks/` (toolz 18, boltons 18), all with template bug reports and 0 leak-check rejections. Log in `results/bench.log`.
- `patchloop eval --model oracle --run-id oracle`: 36/36 resolved. This is a harness sanity check, not a model result.
- `make eval-smoke`: the give-up FakeModel resolves 0/3, and all three are classified `never_found_the_bug`. The viewer renders.
- MCP server: the SDK client fixes the toy bug through the server, and the edit-tests attempt is blocked.

Bugs found and fixed during the build:
- The toy image failed on git's "dubious ownership" check (`COPY --chown` followed by git running as root).
- In the PID-limit test, forked children starved a shared container. That test now gets its own container, and `--init` was added.
- The failure classifier read the trajectory's `end` record as a step.
- The leak-check regex missed "line 17" (the space between "line" and the number).

## Not done / next

- **M5 (E1, E2)**: no API key in this environment. See `docs/PLAN.md` for the exact commands. Nothing is spent without a pilot and approval.
- ADR-008: the effort measurement (low vs medium) is still pending.
- Strategy B tasks and LLM-written reports are implemented but not run (they cost money).
- Hand-review 10 bug reports. Record the README GIF. Replace `seed/my_loop.py` with your own.
