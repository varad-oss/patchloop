"""JSONL trajectories: one line per step. They are the source of truth for every metric."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.I)


def _secret_values() -> list[str]:
    return [v for k, v in os.environ.items() if _SECRET_NAME.search(k) and v and len(v) >= 8]


def redact(text: str, secrets: list[str] | None = None) -> str:
    for value in secrets if secrets is not None else _secret_values():
        text = text.replace(value, "[REDACTED]")
    return text


class Trajectory:
    """Appends JSON lines to `path` (or keeps them in memory when path is None)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self.records: list[dict] = []
        self._secrets = _secret_values()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("")

    def log(self, record: dict[str, Any]) -> None:
        record = {"ts": round(time.time(), 3), **record}
        self.records.append(record)
        if self.path:
            line = redact(json.dumps(record, default=str), self._secrets)
            with self.path.open("a") as f:
                f.write(line + "\n")


def read_trajectory(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
