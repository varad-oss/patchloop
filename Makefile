PY ?= .venv/bin/python
IMG := src/patchloop/sandbox/images
RUN ?= smoke
MODEL ?= claude-haiku-5-5
TOOLSET ?= structured
# Free, local: Ollama on this machine. See docs/DECISIONS.md ADR-011.
LOCAL_MODEL ?= ollama:patchloop-qwen3:8b-16k
EFFORT ?= none
LOCAL_FLAGS := --concurrency 1 --soft-prompt-tokens 12000 --max-wall-s 900

.PHONY: local-model eval-local setup images test test-docker lint bench eval-smoke eval-pilot eval report view demo mcp clean-containers

setup:
	uv venv --python 3.13 .venv && uv pip install --python $(PY) -e ".[dev]"

images:
	docker build -q -t patchloop/toy:latest -f $(IMG)/Dockerfile.toy toy_repo
	docker build -q -t patchloop/toolz:451af60 -f $(IMG)/Dockerfile.repo \
	  --build-arg REPO_URL=https://github.com/pytoolz/toolz --build-arg COMMIT=451af60dec590a6010e2babdbf391ea8f815122f $(IMG)
	docker build -q -t patchloop/boltons:4332b35 -f $(IMG)/Dockerfile.repo \
	  --build-arg REPO_URL=https://github.com/mahmoud/boltons --build-arg COMMIT=4332b35a278d694f30c99881faa61cde695c7a96 $(IMG)

lint:
	$(PY) -m ruff check src tests

test:  ## unit tests, no Docker (what CI runs)
	$(PY) -m pytest -m "not docker"

test-docker:  ## integration + sandbox security tests (needs `make images`)
	$(PY) -m pytest -m docker

bench:  ## generate + validate strategy-A tasks into bench/tasks/ (no API calls)
	$(PY) -m patchloop.cli bench --repo toolz --target 18
	$(PY) -m patchloop.cli bench --repo boltons --target 18

demo:  ## scripted FakeModel fixes the toy bug inside Docker; no API key needed
	$(PY) -m patchloop.cli demo

eval-smoke:  ## 3 tasks with the FakeModel: exercises runner, grader, report, viewer for free
	$(PY) -m patchloop.cli eval --run-id smoke --model fake --limit 3 --yes
	$(PY) -m patchloop.cli report --run-id smoke

eval-pilot:  ## 3 real tasks; prints measured cost per task and the extrapolated total, then stops
	$(PY) -m patchloop.cli eval --run-id $(RUN) --model $(MODEL) --toolset $(TOOLSET) --pilot

eval:  ## full run - only after approving the pilot cost
	$(PY) -m patchloop.cli eval --run-id $(RUN) --model $(MODEL) --toolset $(TOOLSET) --yes

local-model:  ## build the 16K-context qwen3 variant used for free local runs
	ollama pull qwen3:8b
	ollama create patchloop-qwen3:8b-16k -f config/ollama/Modelfile.qwen3-8b-16k

eval-local:  ## free run on the local model, e.g. make eval-local RUN=E1 / RUN=E2 TOOLSET=bash_only
	$(PY) -m patchloop.cli eval --run-id $(RUN) --model $(LOCAL_MODEL) --toolset $(TOOLSET) --effort $(EFFORT) $(LOCAL_FLAGS)

progress:  ## live dashboard for running experiments (read-only)
	$(PY) -m patchloop.cli progress

report:
	$(PY) -m patchloop.cli report --run-id $(RUN)

mcp:
	$(PY) -m patchloop.mcp_server.server

clean-containers:
	docker ps -aq --filter label=patchloop=1 | xargs -r docker rm -f
