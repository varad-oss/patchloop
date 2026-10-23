# PatchLoop spec

_Copied from prompts/P2_PatchLoop_claude_code_prompt.md on 2026-10-23. Changes are recorded as ADRs in DECISIONS.md._

## 0. Who I am, what we are building, and how we work

I am Varad, a B.Tech student at IIT Kharagpur applying for **Agentic AI Intern** roles; deadline **[DATE]**; API budget for this project about **[BUDGET — e.g., $8]**. I write C++ and Go comfortably (a ~2160-Elo chess engine, a Raft key-value store), and I want this project to show the same depth on agents. You are my senior AI-engineering pair. We are building **PatchLoop**: a coding agent written **from scratch** that fixes failing tests inside a locked-down Docker sandbox, evaluated on a benchmark of bugs we inject into real open-source libraries, with its tools also served over MCP.

**The point of this project is to show I understand how agents work under the hood.** So:

- **No agent framework in the core.** No LangChain, LangGraph, LiteLLM, smolagents or similar inside `src/patchloop/agent/`. Official provider SDKs are fine behind my own adapter interface.
- **The core loop stays readable:** `loop.py` ≤ 250 lines, readable top to bottom in ten minutes.
- Start from my hand-written `seed/my_loop.py`; keep its structure where sensible and explain every change you make to it.

### Working agreement

1. **Research before using any library or API** (provider SDKs, Docker SDK, MCP SDK). Check current official docs and record verified versions in `docs/DECISIONS.md`.
2. **Plan first** in plan mode: write `docs/PLAN.md` (milestones, acceptance criteria, estimates); wait for my approval.
3. **One milestone at a time.** At each boundary: run tests, show the demo command, write `docs/learning/M<n>.md` (section 9), update `docs/PROGRESS.md`, commit, then **stop** until I type `continue`.
4. **Tests are the source of truth.** Never weaken or delete tests; never special-case benchmark tasks.
5. **Never fabricate results.** Every reported number comes from `results/` via a Makefile command. Unmeasured = "target".
6. **Ask before spending.** Pilot 3 tasks, print measured cost per task and the extrapolated total, and wait for my OK before any larger run.
7. **Secrets** only in `.env`; never inside containers, logs or trajectories.
8. **Safety first:** agent-issued commands never run on my host machine (section 2.4).
9. **Push back** when the spec is wrong or outdated; record changes as ADRs.
10. **Keep `CLAUDE.md` short**: commands, layout, conventions, pointers to `docs/`.

---

## 1. Goal and scope

Given a Python repository where some tests fail and a short user-style bug report, PatchLoop explores the code, edits it, runs tests inside a sandbox, and submits a patch. A grader checks the patch in a fresh container.

**Non-goals:** competing with state-of-the-art agents, other languages, web browsing, long-running autonomous development.

---

## 2. Architecture

### 2.1 The loop (`src/patchloop/agent/loop.py`)

- Inputs: a task (repo image, bug report, test command) and a config (model, budgets, toolset).
- Each step: build the request (system prompt + task + linear history) → call the model through the adapter → execute any tool calls in the sandbox → append truncated observations → stop on `submit` or any limit.
- **Linear history:** each step only appends (an idea from mini-SWE-agent). Compaction starts a fresh list (2.5) rather than editing history.
- **Budgets** (configurable): max steps 40, max cost per task $0.15, max wall time 10 minutes, soft prompt limit 80K tokens.
- **Stop reasons:** `submitted`, `step_limit`, `cost_limit`, `time_limit`, `model_refusal`, `error` — always recorded.
- **Errors:** tool errors become observations; model API errors (429, 5xx, overloaded) are retried with exponential backoff and jitter; non-retryable errors stop the episode cleanly.
- **Loop detection:** the same action three times in a row triggers one nudge observation; five times stops the episode.
- **Trajectory:** one JSONL line per step — timestamp, step, model text, tool calls, truncated observations, usage (input, output, thinking tokens), cost, latency, stop reason.

### 2.2 Model adapter (`src/patchloop/agent/models.py`)

- One protocol: `complete(system, messages, tools) -> ModelTurn(text, tool_calls, thinking_blocks, usage, stop_reason)`.
- **AnthropicAdapter** using native tool use. For Claude Haiku 5.5 (`claude-haiku-5-5`), follow the official migration guide: send no `temperature`, `top_p` or `top_k`; no assistant prefill; thinking is adaptive and controlled with `output_config.effort` (measure `low` vs `medium` on 5 tasks and pick one); read content blocks by `type`; pass thinking blocks back unchanged with tool results; keep history append-only when thinking blocks are present; handle `stop_reason: "refusal"`; thinking tokens count toward `max_tokens`.
- **OpenAICompatibleAdapter** for Chat Completions–style function calling, so I can use free tiers (Groq, OpenRouter, Gemini's OpenAI-compatible endpoint) for development. Normalise tool-call formats, including parallel tool calls.
- Pricing in a config file with the date checked; cost computed from returned usage. Haiku 5.5 bills $0.10/$0.50 per million input/output tokens for prompts up to 100K tokens and $0.50/$2.50 above — verify before M5.
- **Prompt caching:** the append-only history is cache-friendly. Research whether the chosen model supports caching; if it does, cache the stable prefix and record cache-read tokens and the saving per task.
- Adapter tests use recorded fixtures (no network in CI).

### 2.3 Tools — the agent–computer interface (`src/patchloop/agent/tools.py`)

| Tool | Behaviour |
|---|---|
| `bash(command, timeout_s=60)` | Runs in the sandbox via a fresh `docker exec` per call (stateless, like mini-SWE-agent), cwd `/workspace`. Returns exit code and output truncated to the first 100 + last 50 lines with an explicit `[... N lines truncated ...]` marker. |
| `view_file(path, start_line=1, end_line=None)` | Numbered lines, max 200 per call. |
| `search(pattern, path='.', glob=None)` | ripgrep or grep in the sandbox, max 50 matches with file:line. |
| `str_replace(path, old_str, new_str)` | Exact, unique match required; on 0 or >1 matches return an error with the count; on success show a 5-line snippet around the edit. |
| `run_tests(selector=None)` | Runs the task's test command (or a subset); returns pass/fail summary and truncated failure output. |
| `submit(summary)` | Ends the episode; the harness extracts `git diff`. |

- All paths are resolved inside `/workspace`; traversal is rejected; the tests directory is mounted read-only, so test edits fail.
- Two toolsets for the interface ablation: `structured` (all six) and `bash_only` (`bash` + `submit`).
- Tool descriptions are written for the model: when to use each, what it returns, common errors.

### 2.4 Sandbox (`src/patchloop/sandbox/docker_env.py`)

- One container per episode from a pre-built image per target repository (`python:3.12-slim` + dependencies + repo at a pinned commit).
- Isolation flags (verify exact flag names): no network; memory 1 GB; 1 CPU; PID limit 256; read-only root filesystem with a tmpfs `/tmp`; writable workspace; tests mounted read-only; non-root user; `no-new-privileges`; drop all capabilities; per-command timeout; auto-remove; guaranteed cleanup (context manager, including on Ctrl+C).
- Docker SDK for Python or the `docker` CLI via subprocess — decide in an ADR.
- **Agent commands never run on the host.** Assert this in code and test it. No unsafe fallback, except an explicit `--unsafe-local` flag usable only with `toy_repo/` during M1.
- **Tamper check:** hash test files before and after each episode; any change marks the episode as tampered (counts as unresolved).

### 2.5 Context management (`src/patchloop/agent/context.py`)

- Count tokens with the provider's token-counting endpoint or a documented approximation.
- When the next request would exceed the soft limit (80K tokens — Haiku 5.5's per-token price rises fivefold above 100K-token prompts), **compact**: have the model write a progress summary (files examined, hypotheses, edits made, current test status), then start a **fresh** message list of system prompt + task + summary + the last two observations. Never edit earlier messages in place. Log each compaction in the trajectory and report how often it happened.

### 2.6 Benchmark generator (`src/patchloop/benchgen/`)

- **Target repositories:** two small, permissively licensed, pure-Python libraries whose full test suites run in under ~20 seconds in the container. Research candidates (for example more-itertools, cachetools, toolz, boltons), measure test time, and record choice, licence and pinned commit in an ADR.
- **Strategy A — syntax-tree mutations** (`ast`/`libcst`): flip comparison operators, off-by-one in range or slice bounds, negate a condition, swap arguments, remove a guard clause, change a default value or returned constant, swap `and`/`or`.
- **Strategy B — LLM rewrite** (in the spirit of SWE-smith): pick a function covered by tests; ask a model to reimplement it with one subtle, realistic bug, same signature, no hinting comments.
- **Validation:** the original repo passes all tests; the mutated repo fails at least one test (FAIL_TO_PASS) while the others still pass (PASS_TO_PASS); run twice to exclude flaky tests; de-duplicate identical diffs.
- **Bug reports:** an LLM writes a user-style issue from the failing test names and output only (never the diff). A leak check rejects reports mentioning the mutated file, line number or changed code. I will review ten reports by hand.
- **Difficulty tags:** strategy and mutation type, number of failing tests, lines changed, whether the buggy function is named in a failing test.
- **Output:** `bench/tasks/*.json` with SWE-bench-like fields (`instance_id`, `repo`, `base_commit`, hidden `bug_patch`, `problem_statement`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `image`, `difficulty`). Target 30–40 validated tasks, at least 10 from strategy B if budget allows.
- **Limitation to document:** these libraries are probably in model training data. The injected bugs are new, but familiarity with the original code can help the model.

### 2.7 Evaluation (`src/patchloop/evals/`)

- **Runner:** parallel episodes with a concurrency limit (Docker resources and API rate limits); resumable (skips finished episodes); pilot mode.
- **Grader:** apply the submitted diff to a clean copy in a fresh container; run FAIL_TO_PASS and PASS_TO_PASS. Resolved = all pass and no test files changed.
- **Metrics:** resolve rate with a 95% Wilson interval; mean and median steps, tokens (input, output, thinking), cost per task, wall time; stop-reason distribution; breakdown by difficulty; pass@k and pass^k with unbiased estimators when trials > 1 (unit-test both against hand-computed values).
- **Failure analysis:** classify every unresolved episode (never found the bug, wrong fix, broke other tests, budget exhausted, tool misuse, tamper attempt, infrastructure error) with three annotated examples.
- **Trajectory viewer:** static HTML per run — each step's model text, tool call, observation and the final diff — linked from the report.
- **Experiments** (each run only after my OK on the pilot cost):
  - **E1 Baseline:** Haiku 5.5, `structured` toolset, 1 trial over all tasks.
  - **E2 Interface ablation:** `bash_only` vs `structured`, same tasks and model.
  - **E3 (stretch) Best-of-3** with test-based selection: report pass@3, pass^3 and the cost multiple.
  - **E4 (stretch)** Claude Sonnet 5.5 on a 10-task subset.
- **Report:** `docs/EVAL_REPORT.md` generated from `results/` (tables + charts), including limitations.

### 2.8 MCP server (`src/patchloop/mcp_server/`)

- Expose `bash`, `view_file`, `search`, `str_replace` and `run_tests` over MCP with the **official Python SDK**. As of Oct 2026 the v2 line is the stable release, supports the 2026-07-28 specification, and is what plain `pip install mcp` installs; its server API differs from v1 — read the current docs (py.sdk.modelcontextprotocol.io) before coding.
- One sandbox container per MCP session, created lazily and destroyed on shutdown or idle timeout; same isolation flags.
- Accurate tool descriptions with no hidden instructions; a README note on MCP risks (tool poisoning, over-broad permissions) and how this server limits them.
- Test with the SDK's client against `toy_repo/`; provide config snippets for Claude Desktop and Claude Code; a short recording checklist of Claude fixing a toy bug through the server.

---

## 3. Testing

- **Unit:** tools (traversal blocked, `str_replace` uniqueness, truncation markers), context manager (trigger, fresh-list behaviour), adapters (recorded fixtures), mutators (output parses, exactly one site changed), validation, grader, metrics.
- **Integration:** a scripted FakeModel fixes a known bug in `toy_repo/` end to end in Docker (pytest marker `docker`).
- **Sandbox security tests:** network access fails; writing to tests fails; memory and PID limits enforced; a command cannot touch the host.
- **CI:** Ruff + unit tests without Docker; `docker`-marked tests run locally.

---

## 4. Repository layout

```
patchloop/
  CLAUDE.md  README.md  Makefile  pyproject.toml  .env.example
  seed/my_loop.py                  # my Day-1 loop, kept for reference
  toy_repo/                        # tiny package + tests for demos and integration tests
  src/patchloop/
    agent/ loop.py models.py tools.py context.py prompts.py trajectory.py
    sandbox/ docker_env.py images/
    benchgen/ mutators.py llm_rewrite.py validate.py issues.py
    evals/ runner.py grader.py metrics.py report.py viewer/
    mcp_server/ server.py
  bench/tasks/   results/
  docs/ SPEC.md PLAN.md PROGRESS.md DECISIONS.md ARCHITECTURE.md EVAL_REPORT.md learning/
  tests/ unit/ integration/
```

---

## 5. Milestones and acceptance criteria

| # | Milestone | Est. | Acceptance criteria |
|---|---|---|---|
| M0 | Research, ADRs, scaffold | 1 h | ADRs for provider/adapter design, Docker approach, target repos (with measured test times); CI green. |
| M1 | Loop, adapters, FakeModel | 2–3 h | Built from `seed/my_loop.py`; `loop.py` ≤ 250 lines; budgets, retries, loop detection, trajectories; FakeModel integration test passes on `toy_repo/` (unsafe-local allowed only here). |
| M2 | Sandbox and tools | 2 h | All isolation flags; six tools; security tests pass; FakeModel test now runs in Docker. |
| M3 | Benchmark generator | 3 h | Both strategies, validation, bug reports with leak check; ≥ 30 validated tasks; `make bench`. |
| M4 | Runner, grader, metrics, report, viewer | 2–3 h | `make eval-smoke` (3 tasks) works; pilot cost printed; viewer opens. |
| M5 | Experiments | 2 h + runs | E1 and E2 complete with my approval; report with intervals and failure analysis. |
| M6 | MCP server | 1–2 h | Server + client test; Claude Desktop/Code config; demo checklist. |
| M7 | Docs and demo | 1–2 h | README (section 10); ARCHITECTURE.md with Mermaid (loop sequence diagram, sandbox boundary diagram); demo script. |

**This week's schedule (four projects in seven days).** Day 4, Mon 26 Oct, afternoon: M0–M2, then start M3 and leave `make bench` generating and validating overnight. Day 5, Tue 27 Oct: finish M3, then M4, M5 (E1 and E2) and M6 — run the experiments while I start HopScout in a second session. Day 6, Wed 28 Oct: M7.

**Lean scope for this week** (these override the sections above):

- 30 validated tasks is enough; the CV quotes the real count.
- Strategy B only if strategy A is finished by Day 5 morning. If strategy B is cut, the CV bullet drops "and LLM rewrites".
- E3 and E4 only if E1 and E2 finish early.
- The trajectory viewer can be one static HTML page per run.
- If the MCP server is cut, remove MCP from the CV's PatchLoop bullet and Skills row.

---

## 6. Cut order if we fall behind

E3/E4 → MCP server → strategy-B bugs (keep strategy A) → HTML viewer (keep JSONL + markdown summary). **Never cut:** sandbox isolation and its tests, the grader, E1 with intervals, the learning notes.

---

## 7. Prompts and agent behaviour

- System prompt: role, the tools and when to use each, a recommended workflow (reproduce → localize → hypothesize → minimal fix → run tests → submit), the rule that tests are read-only and must not be special-cased, and the budget.
- Keep the system prompt and tool list constant during an episode (both for clarity and because providers may reject changed history when thinking blocks are present).

---

## 8. Observability

JSONL trajectories are the source of truth. Add a per-run summary (`results/<run_id>/summary.json`) and the HTML viewer. Optional: OpenTelemetry spans named after the GenAI semantic conventions (`invoke_agent`, `execute_tool`) — note those conventions are still marked "Development" status.

---

## 9. Teach me as we go (required)

After each milestone write `docs/learning/M<n>.md`: what we built and why (alternatives, trade-offs); key concepts with pointers to files and functions; how to verify it myself; three interview questions with model answers; one break-it exercise with the expected symptom and how to diagnose it. If I type `quiz me`, ask the questions one at a time and grade my answers honestly.

For M1 also write `docs/learning/LOOP_WALKTHROUGH.md`: the loop annotated line by line, plus the five classic agent-loop failure modes — infinite loops, context overflow, malformed tool calls, silently swallowed tool errors, runaway cost — and exactly where each is handled.

---

## 10. README structure (write in M7)

1. One-line pitch and a GIF of a trajectory being replayed.
2. Results table (E1, E2; optional E3, E4) with model, date, number of tasks and trials, intervals — generated from `results/`.
3. How the loop works: diagram + six bullets.
4. Sandbox design: table of each isolation flag and what it prevents.
5. Benchmark construction: strategies, validation, leak check, limitations (including contamination).
6. Quickstart: fake-model mode with no API key; `make bench`; `make eval-smoke`.
7. MCP demo.
8. How it was built: "Implemented with Claude Code as a pair programmer, starting from my hand-written loop; benchmark design, experiments and analysis by me."

---

## 11. Definition of done

- [ ] `make test` green; Docker security tests pass locally.
- [ ] ≥ 30 validated tasks; E1 and E2 results with intervals committed; report regenerated from results.
- [ ] MCP server works from Claude Desktop or Claude Code (or is cleanly cut with a note).
- [ ] Learning notes for every milestone plus the loop walkthrough.
- [ ] I can write the core loop again from memory in 30 minutes.

---

### Session-start prompt

> Read `CLAUDE.md`, `docs/SPEC.md`, `docs/PLAN.md` and `docs/PROGRESS.md`. Summarize where we are in 5 bullets, then continue with the next step of the current milestone under the working agreement. Stop at the milestone boundary.

### Milestone-review prompt

> Before I type `continue`: list each changed file with one line on why; show the test output; name the two places most likely to break in a live demo and how to check them; then quiz me with the three questions from the learning note.
