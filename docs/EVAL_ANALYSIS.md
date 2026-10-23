# Evaluation analysis (E1, E2)

Interpretation of [EVAL_REPORT.md](EVAL_REPORT.md). Every number below is taken from that generated report or
from the trajectories in `results/`. Runs: 2026-10-23/24, local `qwen3:8b` (Q4_K_M) through Ollama 0.40.8,
16K context, thinking off, Apple M5 / 16 GB, GPU not shared with other jobs, cost $0 (ADR-011).

## Headline

| run | toolset | resolved | 95% Wilson CI |
|---|---|---|---|
| E1 | structured (6 tools) | **12/36 = 33.3%** | 20.2%-49.7% |
| E2 | bash only | **3/36 = 8.3%** | 2.9%-21.8% |

**Paired on the same 36 tasks:** 11 tasks were solved only with the structured toolset, 2 only with bash, and 1
by both. The exact McNemar test on those 13 discordant tasks gives **p = 0.022**. For this 8B model, the structured
agent-computer interface is a real effect, not noise. Treat it as model-dependent: stronger models often do as well
with bash alone (the mini-SWE-agent observation). This experiment says nothing about them.

## What separates the two toolsets

Localization is not the problem. In every episode of both runs the model mentioned the buggy file in some tool
call (it follows the failing tests there). The gap is in **editing**:

- E1 edited the buggy file in 20/36 episodes; E2 in 10/36.
- Of the unresolved episodes, 16/24 (E1) and 25/33 (E2) ended with an **empty patch**: the model read code until
  its budget ran out and never changed anything.
- With bash only, every edit has to be a `sed`/`python -c`/heredoc one-liner. The 8B model rarely commits to one.
  With `str_replace` it edits, gets a precise error ("occurs 0 times" plus the closest region, ADR-012) or a
  snippet of the result, and iterates.

## Three annotated failures

### 1. E1, wrong fix, submitted with failing tests: `boltons__rotate_file-swap_args-015`

The injected bug turned `range(1, keep + 1)` into `range(keep + 1, 1)`, an empty range.

| step | action | note |
|---|---|---|
| 1 | `run_tests` on the 3 failing tests | 3 failed, `IndexError` on `kept_names[-1]` |
| 2-7 | `search`, `view_file` | finds `rotate_file`, reads the loop. Steps 4 and 6 are no-tool "thinking out loud" turns |
| 9-10 | `str_replace` | 0 matches: wrong indentation |
| 11 | `str_replace` -> `range(keep, 0, -1)` | the right line, but **reversed** where it should be swapped back |
| 12-27 | edits a different block three times, re-runs tests | still `3 failed` every time |
| 29 | `submit` | **submits while the tests still fail** |

Two lessons. The model found the exact buggy line but "fixed" it into another plausible-looking range. And it
ignored the system prompt's rule to submit only after tests pass. The harness can't stop that, but the grader
catches it (`fail_to_pass_still_failing`). Notably, E2 *resolved* this task with bash only.

### 2. E1, ran out of steps with no edit: `boltons___get_apparent_index-compare_flip-001`

40 steps: 1 `run_tests`, 15 `search`, 24 `view_file`, **0 edits**, and **3 compactions**. After each compaction
(the 12K-token soft limit on a 16K window), the fresh context holds the model's own summary plus the last two
observations, and the model starts re-reading `setutils.py` from the top. The last 8 calls are all
`search`/`view_file` on that same file. This is context-reset amnesia: the summary carried "what I looked at" but
not a decision.

Across runs, compaction tracks failure: resolved 4/22 with compaction vs 8/14 without in E1 (0/21 vs 3/15 in E2).
That is correlation, since hard tasks run long and compact, but this trajectory shows a plausible mechanism.
Candidate fixes: a larger context (needs more RAM), or a summary prompt that asks for "the next concrete edit".

### 3. E2, stopped by the loop detector: `boltons__find_all_links-off_by_one-002`

Nine bash calls: `grep -rl`, then `cat -n` of the whole `urlutils.py` (truncated to first 100 + last 50 lines, so
the relevant function is in the cut middle), then `grep -A 10 'find_all_links' boltons/urlutils.py` **five times
in a row**. The detector nudged at the third repeat ("re-read the latest observation, consider a different
hypothesis"); the model repeated twice more and was stopped at five, as designed. Raw `cat` of a large file plus
middle-truncation hides exactly the code it needed. `view_file` with line ranges exists in E1 for this reason.

## Other observations

- **Thinking on vs off (ADR-008 replacement).** With thinking on, 0/5 resolved, every episode hitting the 15-minute
  limit after 6-17 steps (`results/effort-low-r3`). Each step takes about a minute of thinking on this hardware.
  Thinking off resolved 2/5 of the same tasks earlier (with the pre-ADR-012 tools), and E1 resolved 3/5 of them.
  On a laptop GPU, thinking off is the only practical mode for an agent loop.
- **Idle turns.** 10% (E1) and 11% (E2) of steps had no tool call: the model narrates a plan and stops. The nudge
  recovers it, at the cost of a step.
- **Resolved without submitting.** `toolz__topk-bool_op_swap-006` (E1) was stopped by the loop detector after it
  had already made the correct fix. It was re-running the same check instead of calling `submit`. The grader scores
  the final diff, so it counts as resolved (SWE-bench-style grading).
- **Speed.** E1 averaged 240 s per episode and E2 308 s. With the GPU shared with another project's eval earlier,
  episodes took about 10 minutes, and more of them hit the time limit.
- **Time-limit overshoot.** The wall-time limit is checked between steps, so a slow model call can overrun it. One
  thinking-on episode ran 1,213 s against a 900 s limit.

## Caveats

- **Model.** These are results for a local 8B model, not Claude Haiku 5.5 as the spec planned; a paid API was ruled
  out (ADR-011). Absolute rates are not comparable to published agent benchmarks.
- **Classifier gap.** `bash` reports `is_error` only on timeouts (a non-zero exit code is a normal observation), so
  the `tool_misuse` class cannot fire in E2. Both runs' failure classes collapse into `budget_exhausted`. The
  diagnostics table above is more informative.
- **Interface change disclosed.** ADR-012 (closest region on a failed `str_replace`) was added after looking at 5
  pilot trajectories, before E1 and E2.
- One trial per task; contamination and synthetic-bug limitations as listed in the report.
