# Decisions (ADRs)

Each ADR records a choice, the alternatives considered, and why. Versions were verified on 2026-10-23
against PyPI and the installed packages.

## Verified versions

| Component | Version | How verified |
|---|---|---|
| Python (host venv) | 3.13.14 | `uv python list` |
| Python (sandbox images) | 3.12 (`python:3.12-slim`) | Dockerfile |
| `anthropic` | 2.1.0 | PyPI JSON API; installed package inspected (`Usage.output_tokens_details.thinking_tokens`, top-level `cache_control`, `output_config`) |
| `openai` | 3.37.0 | PyPI JSON API |
| `mcp` | 2.3.0 (v2 line; `FastMCP` renamed `mcp.server.mcpserver.MCPServer`; `mcp.Client`) | PyPI; read `mcp/server/fastmcp.py` stub + `MCPServer`/`Client` source |
| `pytest` / `ruff` | 9.1.1 / 0.17.2 | PyPI |
| Docker Engine | 29.7.2 (Docker Desktop, macOS arm64) | `docker info` |
| toolz | 1.2.0 @ `451af60` | `git rev-parse` of the tag inside the build container |
| boltons | 26.2.0 @ `4332b35` | same |

---

## ADR-001 Model adapter design

**Decision.** One `ModelAdapter` protocol, `complete(system, messages, tools) -> ModelTurn(text, tool_calls,
thinking_blocks, usage, stop_reason, raw)`, with `AnthropicAdapter`, `OpenAICompatibleAdapter` and a scripted
`FakeModel`. The loop keeps a provider-neutral history; each adapter converts it to its wire format. The
assistant turn keeps the provider's `raw` content so it can be replayed byte-for-byte.

**Why.** Claude Haiku 5.5 binds thinking blocks to the exact preceding history and to the account; the
safe rule is "pass `response.content` back unchanged, never edit earlier turns". Storing `raw` makes that
automatic. No LiteLLM-style layer: the conversion is ~40 lines per provider and is part of what this project
demonstrates.

**Haiku 5.5 request surface** (from the Anthropic migration guide, read 2026-10-23):
- `thinking: {"type": "adaptive"}`; depth via `output_config.effort` (default `medium`; we default to `low`,
  see ADR-008). `budget_tokens` → 400. No `temperature`/`top_p`/`top_k` (non-defaults → 400). No prefill.
- Content is read by block `type`; thinking blocks come back with empty text + signature by default and are
  replayed unchanged. Thinking tokens count toward `max_tokens` (we use 16,000).
- `stop_reason == "refusal"` is handled (episode stops with `model_refusal`). Haiku 5.5 has no server-side
  fallback, so none is configured.
- SDK retries are disabled (`max_retries=0`): the loop owns retries so every retry is in the trajectory.

**Alternatives.** Anthropic's Tool Runner (rejected: the point is to own the loop); LiteLLM (forbidden by spec).

## ADR-002 Docker via the CLI, not the Docker SDK

**Decision.** `subprocess` calls to the `docker` CLI, all funnelled through one function (`_run_docker`) that
asserts the argv is a docker subcommand from an allow-list.

**Why.** Flags map 1:1 to the documentation (easy to audit against the isolation table), no extra dependency,
and the single choke point makes "agent commands never run on the host" a one-line assertion that is
unit-tested (`tests/unit/test_sandbox_unit.py`). The Docker SDK (7.2.0) would work equally well; the cost is
~100 ms per `docker exec`, irrelevant next to model latency.

## ADR-003 Sandbox layout

- Workspace: an **anonymous volume** at `/workspace`, populated by Docker from the image, removed with the
  container (`--rm`). Lets the root filesystem be `--read-only`.
- Tests: a host copy of the image's tests directory, extracted once per image, **bind-mounted read-only** over
  the workspace's tests directory.
- **Fresh git history** at container start (`rm -rf .git && git init && commit`), after the bug patch is
  applied. Without this the agent could `git diff HEAD` its way to the injected bug.
- `--init` added after the PID-limit test showed orphaned processes accumulating in a long-lived container.
- Per-command timeout with `timeout -k 2 <s>` inside the container plus a host-side subprocess timeout.

## ADR-004 Target repositories: toolz and boltons

Measured inside `python:3.12-slim`, full suite, one run (2026-10-23):

| candidate | licence | tests | time | verdict |
|---|---|---|---|---|
| toolz 1.2.0 | BSD-3-Clause | 192 | 0.4 s | **chosen** - pure functions, clear tests |
| boltons 26.2.0 | BSD-3-Clause | 519 | 1.8 s | **chosen** - many independent modules |
| cachetools 7.2.4 | MIT | 366 | 0.2 s | good backup; narrower domain (caches) |
| more-itertools 11.2.1 | MIT | 765 + 21k subtests | 13.9 s | rejected: validation runs each candidate twice |

Pinned commits are in `config/repos.toml`.

## ADR-005 Stop reasons: added `loop_detected`

The spec lists `submitted, step_limit, cost_limit, time_limit, model_refusal, error` and says five identical
actions stop the episode. That stop deserves its own label rather than being folded into `error`, so failure
analysis can tell "stuck" from "crashed". Pushed back; added `loop_detected`.

## ADR-006 Token counting

Exact where it matters: every response reports the prompt size (`input + cache_read + cache_write`). The
tracker anchors on that and adds `chars / 3.5` for messages appended since the last call. The count-tokens
endpoint would cost a round trip per step for a number we get for free one step later. The approximation
over-estimates for code, which only makes compaction trigger slightly early.

## ADR-007 Benchmark: template bug reports by default

The LLM issue writer exists (`patchloop bench --issues llm --yes`) but costs money, so the committed 36 tasks
use the deterministic template writer: failing test ids + a filtered failure excerpt (test-file frames and `E`
lines only; library frames dropped). Both pass through the same leak check. Strategy B (LLM rewrite) is
implemented but was not run (no API key in this environment; needs approval).

## ADR-008 Effort level

**Update 2026-10-24 (measured, local model):** with qwen3:8b, thinking on (`--effort low`) resolved 0/5 with every
episode at the 15-minute limit (`results/effort-low-r3`); thinking off (`--effort none`) is the setting for E1/E2.
The Claude low-vs-medium measurement below still applies to anyone running with a key.

Spec: measure `low` vs `medium` on 5 tasks and pick one. **Not yet measured** (no API key available during the
build). Default is `low` because it is the cheapest; run
`patchloop eval --run-id effort-low --effort low --limit 5 --pilot` and the same with `medium`, then record the
choice here.

## ADR-009 Grader hardening

Besides read-only tests, the grader rejects diffs touching `conftest.py`, pytest/tox/setup config,
`sitecustomize.py`, or `.pth` files: all ways to change test outcomes without fixing code. A tests-hash taken
before and after each episode marks tampering.

## ADR-010 Seed loop

The Day-1 hand-written `seed/my_loop.py` was not in the repo when the build began. Claude wrote a stand-in in the
same spirit (~120 lines). `docs/learning/LOOP_WALKTHROUGH.md` maps seed → `loop.py`. Replace it with your own.

## ADR-011 Experiments run on a free local model (Ollama), not a paid API

**Context.** Varad's constraint (2026-10-23): no API key and no paid service. Everything runs free.

**Decision.** E1/E2 run on `qwen3:8b` (Q4_K_M, 8.2B parameters) served locally by Ollama 0.40.8, through the existing
`OpenAICompatibleAdapter` at `http://localhost:11434/v1` (model spec `ollama:<name>`). No new adapter code was
needed beyond passing `reasoning_effort`. The provider-neutral adapter design (ADR-001) is what made this a
config change.

- **Context window.** Ollama's default context is too small for an agent transcript, and it *silently drops the
  start* of an over-long prompt. `config/ollama/Modelfile.qwen3-8b-16k` sets `num_ctx 16384`. KV cache is about
  147 KB/token (36 layers x 8 KV heads x 128 dims x 2 x fp16), about 2.4 GB at 16K, which fits next to the Docker VM on
  a 16 GB M5. The compaction threshold is set to 12,000 tokens, and every observation is capped at 20,000 characters.
- **Thinking.** qwen3's thinking is switched with `reasoning_effort`: `none` = off, `low` = on. This replaces
  ADR-008's low-vs-medium measurement (see the result below).
- **Concurrency 1**, because one local model serves requests one at a time. Wall-time limit raised to 900 s per
  episode, since local inference is slower than an API.
- **Cost is $0** for every run. The Claude adapter, pricing table and pilot gate stay in place and tested, for
  anyone who does have a key.

**Consequences.** Absolute resolve rates are for an 8B local model, not Claude Haiku 5.5. The CV/README must say so.

## ADR-012 `str_replace` shows the closest region on a failed match

**Evidence.** In the thinking-off effort check (`results/effort-none`), `boltons__backoff_iter-compare_flip-017`
burned 14 of 40 steps re-sending an `old_str` the model had paraphrased from memory (wrong condition order,
merged string literals). The error said only "occurs 0 times".

**Decision.** On 0 matches, `str_replace` appends the most similar block of the file (difflib over windows the size
of `old_str`, whitespace-insensitive, shown only when similarity >= 0.5) with line numbers, and says to copy it
exactly. This is a general interface change in the spirit of SWE-agent's agent-computer interface work. It is not
specific to any task.

**Disclosure.** The change was made after seeing 5 pilot trajectories and before E1/E2. E1 and E2 both use it. The
effort check (`effort-none`, `effort-low`) ran on the earlier version.

## ADR-013 Strategy B (LLM-rewrite bugs) generated with the local model, not evaluated

**What ran.** `scripts/run_strategy_b.sh` with `qwen3:8b` (thinking off, replies capped at 2,000 tokens). The 8B model
often returned the function unchanged, so the prompt asks it to state the bug on a `BUG:` line first (discarded,
never shown to the agent), and an identical rewrite gets one retry. Each candidate then goes through the same
validation as strategy A (fails specific tests twice, consistently) and the same leak-checked template bug report.

**Result.** 9 candidates were accepted before the run was stopped, so Ollama could be handed to another project.
- 6 toolz tasks are clean single-line bugs (`while True` -> `while False`, `seq[-n:]` -> `seq[-n-1:]`, ...). They are in
  `bench/tasks_llm/`, and the oracle resolves 6/6 (`results/oracle-llm`).
- 3 boltons tasks exposed a splicing bug: methods returned with their own indentation were indented twice, turning
  a one-line bug into a 10-26-line whitespace diff. They were set aside in `bench/tasks_llm_rejected/`. Fixed:
  model code is now dedented before parsing, and rewrites changing more than 4 lines are rejected (both unit-tested).

**Not done.** The agent was not evaluated on the strategy-B tasks (an "E1b" run). That needs the GPU and is left as
future work: `patchloop eval --run-id E1b --tasks-dir bench/tasks_llm ...`. The headline benchmark stays the 36
strategy-A tasks. Six is below the spec's "at least 10 from strategy B if budget allows".
