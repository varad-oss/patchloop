# Plan

Per Varad's instruction (2026-10-23), the build ran straight through without stopping at milestone
boundaries. The learning notes are written for study afterwards. The pilot-before-spending rule still holds.

| # | Milestone | Acceptance criteria | Status |
|---|---|---|---|
| M0 | Research, ADRs, scaffold | Verified versions; ADRs for adapters, Docker, target repos (measured); CI config | done |
| M1 | Loop, adapters, FakeModel | `loop.py` <= 250 lines (200); budgets, retries, loop detection, trajectories; FakeModel test on toy_repo (unsafe-local and Docker) | done |
| M2 | Sandbox + tools | All isolation flags; 6 tools; security tests pass; FakeModel test in Docker | done |
| M3 | Benchmark generator | Strategies A + B implemented; validation; leak-checked reports; >= 30 tasks; `make bench` | done (36 tasks, strategy A; B not run - needs API) |
| M4 | Runner, grader, metrics, report, viewer | `make eval-smoke` works; pilot cost printed; viewer opens | done (oracle 36/36) |
| M5 | Experiments E1, E2 | Results with intervals and failure analysis, after pilot approval | done on a free local model (ADR-011): E1 33.3%, E2 8.3%, p = 0.022 |
| M6 | MCP server | Server + SDK-client test; configs; demo checklist | done |
| M7 | Docs and demo | README, ARCHITECTURE (Mermaid), demo script | done (GIF to record) |

## How M5 was run

Free, on the local model: `scripts/run_local_experiments.sh` (thinking-on check, then E1, then E2), then
`patchloop report --all`. To repeat on Claude with a key: `make eval-pilot RUN=E1`, approve the cost, `make eval RUN=E1`.
