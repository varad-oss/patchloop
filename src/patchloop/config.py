"""Repository paths and repo config."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = ROOT / "bench" / "tasks"
RESULTS_DIR = ROOT / "results"


def repos() -> dict[str, dict]:
    with open(ROOT / "config" / "repos.toml", "rb") as f:
        return tomllib.load(f)["repos"]


def load_tasks(task_dir: Path = TASKS_DIR, ids: list[str] | None = None) -> list[dict]:
    tasks = [json.loads(p.read_text()) for p in sorted(Path(task_dir).glob("*.json"))]
    if ids:
        tasks = [t for t in tasks if t["instance_id"] in ids]
    return tasks
