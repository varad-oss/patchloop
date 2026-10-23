# Loop walkthrough: `src/patchloop/agent/loop.py`

Read this with the file open. The aim is to be able to rewrite the loop from memory in 30 minutes.

## From seed to loop

| `seed/my_loop.py` | `agent/loop.py` | why it changed |
|---|---|---|
| Anthropic SDK called directly | `model.complete(...)` via `ModelAdapter` | swap providers; FakeModel for tests |
| `messages` holds SDK objects | neutral history + `raw` per assistant turn | provider-independent; thinking blocks replayed byte-for-byte |
| `MAX_STEPS` only | `Budget`: steps, cost, wall time, soft prompt tokens, retries | real agents fail by running out of money or time, not just steps |
| retry `2**attempt`, no jitter, swallowed | `call_with_retries`: backoff + jitter, `retry-after`, logged, gives up into `error` | thundering herd; visible retries |
| bash only, inline | `Toolbox` with 6 tools, errors as observations | the interface ablation (E2) needs both toolsets |
| `print` | `Trajectory` JSONL with usage, cost, latency | every metric is computed from trajectories |
| none | `LoopDetector`, compaction, refusal, no-tool nudge | the classic failure modes (below) |

## Line by line

- **L33 `STOP_REASONS`**: the closed set of ways an episode can end. Every exit path goes through `finish()`, so a stop reason is always recorded.
- **L37 `Budget`**: defaults from the spec. `soft_prompt_tokens=80_000` sits below Haiku 5.5's 100K price step (input price is 5x above it).
- **L46 `EpisodeResult`**: what the runner persists. `tool_errors / tool_calls` feeds the "tool misuse" classifier.
- **L64 `LoopDetector`**: hashes the *whole action* (all tool calls with arguments, keys sorted). The 3rd identical action in a row gets one nudge, the 5th returns `stop`. `nudged` resets when the action changes, so a new loop gets its own nudge.
- **L89 `call_with_retries`**: only `RetryableModelError` is retried (the adapters map 408/409/429/5xx/529/connection errors to it). The delay is `retry-after` if the server sent one, else `min(60, 2·2^attempt)` times a jitter factor in `[0.5, 1.5]`. After `max_retries` it raises `FatalModelError`, which the loop turns into stop reason `error`. `sleep` is injected so tests run instantly.
- **L107 `run_episode`**: builds the system prompt and tool specs **once**; they never change during an episode (cache prefix + thinking-block validity).
- **L124 `finish`**: the single exit. Logs an `end` record with the full result.
- **L130 `account`**: cost of every call (including compaction calls) is computed from the usage *the API returned*, through `config/pricing.toml`.
- **L136 the loop**: checks wall time before spending another call.
- **L140 (1) compaction**: if the tracker estimates the next prompt is over the soft limit, the model writes a progress summary and `messages` is *replaced by a new list*: task + summary + last two observations. The old list is never edited.
- **L151 (2) model call**: the assistant turn is appended *with `raw`*. `tracker.record` anchors the token estimate on the real `usage`.
- **L166 refusal**: Haiku 5.5's safety classifiers can return `stop_reason: "refusal"` (HTTP 200). This is checked before tool calls are looked at.
- **L168 (3) no tool call**: append a nudge and spend the step. Because the step counter still advances, a model that keeps chatting can't loop forever. If it stopped on `max_tokens`, the nudge says so.
- **L179 (4) tool execution**: calls run in order. Each one gets exactly one result, even after `submit` ("Ignored"); providers reject a tool_use without a matching tool_result. Errors (bad path, 0 matches, timeouts, malformed JSON) come back with `is_error=True`, never as exceptions.
- **L195 (5) loop detection**: the nudge is appended *after* the tool results. The Anthropic adapter merges it into the same user turn.
- **L202 (6) stop conditions**: submit, then loop, then cost. Falling out of the `for` loop means `step_limit`.

## The five classic failure modes, and where each is handled

| failure mode | symptom | handled at |
|---|---|---|
| **Infinite loops** | same command forever; or chatting without tools | `LoopDetector` (L64, used L195-206); no-tool nudge still spends a step (L168); hard `max_steps` (L136, L209) |
| **Context overflow** | 400 "prompt too long", or silent cost blow-up past 100K tokens | observation truncation `tools.truncate` (100 head + 50 tail lines, 2000 chars/line); `ContextTracker` + `compact()` (L140; `agent/context.py`) |
| **Malformed tool calls** | invalid JSON args, unknown tool, missing args, output cut by `max_tokens` | `OpenAICompatibleAdapter.parse` sets `parse_error`; `Toolbox.execute` turns parse errors, unknown names and `TypeError` into error observations; `max_tokens` nudge (L171) |
| **Silently swallowed tool errors** | the model thinks an edit worked when it didn't | every tool returns an `Observation` with `is_error`; `str_replace` reports the match count and shows the edited lines; `tool_errors` is counted and logged per step |
| **Runaway cost** | an episode spends dollars | `cost_usd` from real usage after every call (L130); `cost_limit` checked every step (L176, L207); soft prompt limit keeps calls on the cheap price card; runner pilot gate in `cli.py` |

## Rewrite-from-memory checklist

1. A budget dataclass and a stop-reason set.
2. `messages = [task]`; `for step in range(max_steps)`.
3. Time check → compaction check → model call with retries → append the assistant turn (raw).
4. Refusal? Stop. No tool calls? Nudge and continue.
5. Execute every call in order, collect results, append them as one tool message.
6. Loop detector → log the step → submit / loop / cost checks.
7. Fall-through → `step_limit`.
