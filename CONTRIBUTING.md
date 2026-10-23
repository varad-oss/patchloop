# Contributing

Thanks for your interest. Issues and small pull requests are welcome.

## Setup

```bash
make setup                  # Python 3.13 venv via uv, installs the package with dev extras
make images                 # Docker images for the toy repo, toolz and boltons
make test                   # unit tests: no Docker, no model, no network
make test-docker            # sandbox security and end-to-end tests (needs Docker)
make lint
```

For anything that runs a real model, install [Ollama](https://ollama.com) and run `make local-model`.

## Ground rules

- **Tests are the source of truth.** Don't weaken, skip or delete a test to make a change pass.
- **No special-casing benchmark tasks.** Fixes to the agent or its tools must be general.
- **Agent commands never run on the host.** Everything goes through `DockerEnv`; `_run_docker` asserts it.
  `--unsafe-local` is only for the bundled `toy_repo/`.
- **Every reported number comes from `results/`.** Never edit `docs/EVAL_REPORT.md` by hand; run `patchloop report --all`.
- **The core loop stays readable.** `src/patchloop/agent/loop.py` stays under 250 lines, and no agent framework in `agent/`.
- **Free by default.** No command, test or demo may require a paid API key.

## Adding benchmark tasks

`patchloop bench --repo <toolz|boltons> --target N` (strategy A, no model needed) or `--strategy llm --model
ollama:<model>` (strategy B). Every accepted task is validated twice and leak-checked; then run the oracle
(`patchloop eval --model oracle --tasks-dir <dir> --run-id <id>`), which must resolve 100%.

Design background: [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
