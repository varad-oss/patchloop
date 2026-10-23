#!/usr/bin/env bash
# Free local experiments, one project at a time on the GPU.
# Waits until no other project's eval is using Ollama, then runs: thinking-on check -> E1 -> E2.
# Resumable: finished episodes are skipped if this is re-run.
set -u
cd "$(dirname "$0")/.."
M=ollama:patchloop-qwen3:8b-16k
FLAGS=(--concurrency 1 --soft-prompt-tokens 12000 --max-wall-s 900)
OTHERS="trustdesk eval|hopscout eval|agentwal eval"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

log "waiting for other projects' evals to finish (pattern: $OTHERS)"
while pgrep -f "$OTHERS" >/dev/null; do sleep 30; done
log "GPU free; starting"

.venv/bin/python -m patchloop.cli eval --run-id effort-low-r3 --model "$M" --effort low --limit 5 "${FLAGS[@]}" 2>&1 | tail -3
log "thinking-on check done"
.venv/bin/python -m patchloop.cli eval --run-id E1 --model "$M" --effort none --toolset structured "${FLAGS[@]}" 2>&1 | tail -3
log "E1 done"
.venv/bin/python -m patchloop.cli eval --run-id E2 --model "$M" --effort none --toolset bash_only "${FLAGS[@]}" 2>&1 | tail -3
log "E2 done"
