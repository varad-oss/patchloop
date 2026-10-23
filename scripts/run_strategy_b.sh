#!/usr/bin/env bash
# Strategy B (LLM-rewrite bugs) with the free local model, kept separate from the 36 strategy-A tasks.
set -u
cd "$(dirname "$0")/.."
M=ollama:patchloop-qwen3:8b-16k
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
log "generating strategy-B tasks"
for repo in toolz boltons; do
  .venv/bin/python -u -m patchloop.cli bench --repo "$repo" --strategy llm --model "$M" --target 6 \
    --max-attempts 40 --seed 7 --out-dir bench/tasks_llm 2>&1 | grep -E "accepted|rejected|source files|tasks accepted"
done
log "oracle check on strategy-B tasks"
.venv/bin/python -m patchloop.cli eval --run-id oracle-llm --model oracle --tasks-dir bench/tasks_llm 2>&1 | tail -2
log "E1 configuration on strategy-B tasks (E1b)"
.venv/bin/python -m patchloop.cli eval --run-id E1b --model "$M" --effort none --toolset structured \
  --tasks-dir bench/tasks_llm --concurrency 1 --soft-prompt-tokens 12000 --max-wall-s 900 2>&1 | tail -2
log "done"
