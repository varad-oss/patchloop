"""User-style bug reports, written from the failing tests ONLY - never from the diff.

Two writers share one input (failing test ids + a filtered failure excerpt) and one leak check:
  - template: deterministic, free; the default.
  - llm: a model writes a natural issue (opt-in, costs API money).
The leak check rejects any report that names the mutated file, its line number, or the changed code.
"""

from __future__ import annotations

import re

from ..agent.models import ModelAdapter

ISSUE_SYSTEM = """You write GitHub issues as a user of an open-source Python library would.
You are given the names of tests that started failing and an excerpt of their failure output.
Write a short issue (title line, then 3-8 sentences, optionally a tiny code example) describing the
wrong behaviour as a user would observe it. Do not guess at the cause, do not name source files or
line numbers, and do not propose a fix. Output only the issue text."""


def failure_excerpt(output: str, tests_dir: str, max_lines: int = 25) -> str:
    """Keep the parts of a --tb=short failure a user would see: test-file frames and `E` lines.
    Frames inside library code (which would point at the bug) are dropped."""
    keep, keep_next = [], False
    for line in output.splitlines():
        s = line.rstrip()
        if keep_next:
            keep.append(s)
            keep_next = False
            continue
        frame = re.match(r"^(\S+\.py):\d+: in ", s)
        if frame:
            if frame.group(1).startswith(tests_dir) or "/tests/" in frame.group(1) or "test_" in frame.group(1):
                keep.append(re.sub(r":\d+: in ", " in ", s))
                keep_next = True
            continue
        if s.startswith("E "):
            keep.append(s)
    return "\n".join(keep[:max_lines])


def _tested_names(fail_to_pass: list[str]) -> list[str]:
    names = []
    for t in fail_to_pass:
        fn = t.split("::")[-1].split("[")[0]
        fn = fn.removeprefix("test_")
        if fn and fn not in names:
            names.append(fn)
    return names


def template_issue(fail_to_pass: list[str], excerpt: str) -> str:
    names = _tested_names(fail_to_pass)
    title = f"Unexpected behaviour in {', '.join('`' + n + '`' for n in names[:3])}"
    tests = "\n".join(f"- `{t}`" for t in fail_to_pass[:8])
    more = f"\n- ... and {len(fail_to_pass) - 8} more" if len(fail_to_pass) > 8 else ""
    return (f"{title}\n\nOn the current checkout some of the library's own tests fail:\n{tests}{more}\n\n"
            f"The failures look like this:\n```\n{excerpt or '(no assertion output)'}\n```\n\n"
            "These tests passed before, and I expected them to pass. Could you take a look?")


def llm_issue(model: ModelAdapter, fail_to_pass: list[str], excerpt: str) -> tuple[str, object]:
    prompt = ("Failing tests:\n" + "\n".join(fail_to_pass[:10]) +
              f"\n\nFailure output (excerpt):\n{excerpt}\n\nWrite the issue.")
    turn = model.complete(ISSUE_SYSTEM, [{"role": "user", "content": prompt}], [])
    return turn.text.strip(), turn


def leak_check(issue: str, path: str, lineno: int, original_line: str, mutated_line: str) -> list[str]:
    """Return the reasons the issue leaks the bug's location (empty list = clean)."""
    reasons = []
    base = path.rsplit("/", 1)[-1]
    if path in issue:
        reasons.append(f"mentions file {path}")
    if re.search(rf"(?<![\w/]){re.escape(base)}", issue) and not re.search(rf"test_{re.escape(base)}", issue):
        reasons.append(f"mentions file {base}")
    if re.search(rf"(\bline\s*|\bL|:){lineno}\b", issue):
        reasons.append(f"mentions line {lineno}")
    for label, code in (("original", original_line.strip()), ("mutated", mutated_line.strip())):
        if len(code) >= 10 and code in issue:
            reasons.append(f"quotes the {label} code {code!r}")
    return reasons
