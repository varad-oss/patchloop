"""Parse per-test outcomes from `pytest -rA` short-summary lines."""

from __future__ import annotations

import re

_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS) (.+?)(?: - .*)?$")
RESULT_FLAGS = "-rA -q --tb=no --color=no -o console_output_style=classic"


def parse_outcomes(output: str) -> dict[str, str]:
    """nodeid -> PASSED | FAILED | ERROR | XFAIL | XPASS. SKIPPED lines carry no nodeid and are ignored."""
    out: dict[str, str] = {}
    for line in output.splitlines():
        m = _LINE.match(line.strip())
        if m and "::" in m.group(2):
            nodeid = m.group(2).strip()
            if m.group(1) == "ERROR" and nodeid.startswith("at "):
                continue
            out.setdefault(nodeid, m.group(1))
    return out


def passed(outcomes: dict[str, str]) -> set[str]:
    return {k for k, v in outcomes.items() if v in ("PASSED", "XFAIL")}
