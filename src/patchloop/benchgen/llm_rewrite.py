"""Strategy B (in the spirit of SWE-smith): a model reimplements one function with one subtle bug.

Opt-in: costs API money, so `patchloop bench --strategy llm` refuses to run without --yes.
Checks before validation: same signature, parses, no hinting comments, actually different.
"""

from __future__ import annotations

import ast
import difflib
import random
import re
import textwrap
from dataclasses import dataclass

from ..agent.models import ModelAdapter
from .mutators import Mutation

REWRITE_SYSTEM = """You help build a benchmark for debugging agents. You will be given one Python function.
Rewrite it so that it keeps the exact same signature and almost the same behaviour, but contains ONE
subtle, realistic bug of the kind a careful developer might write (wrong boundary, missed edge case,
wrong variable, inverted condition, wrong default). Rules: same name and parameters; do not add or
change comments or docstrings; no comments hinting at the bug; keep the style of the original.
Reply in exactly this format:
BUG: <one sentence: which expression you change and how>
```python
<the complete rewritten function>
```
The BUG line is for the benchmark authors only and is never shown to anyone debugging the code."""

RETRY_IDENTICAL = ("Your rewrite behaves exactly like the original - nothing was changed. Apply the bug you "
                   "described: actually change that expression. Reply in the same format.")

MAX_CHANGED_LINES = 4  # also catches whitespace churn from mis-indented model output

HINT_WORDS = re.compile(r"#.*\b(bug|fix|wrong|subtle|incorrect|error|introduced|mistake)\b", re.I)


@dataclass
class FunctionSite:
    path: str
    name: str
    node: ast.FunctionDef
    source: str


def function_sites(files: dict[str, str], min_lines: int = 4, max_lines: int = 40) -> list[FunctionSite]:
    sites = []
    for path, src in sorted(files.items()):
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("__") and \
                    min_lines <= n.end_lineno - n.lineno + 1 <= max_lines and not n.decorator_list:
                sites.append(FunctionSite(path, n.name, n, ast.get_source_segment(src, n) or ""))
    return sites


def _extract_code(text: str) -> str | None:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return m.group(1) if m else None


def rewrite(model: ModelAdapter, files: dict[str, str], site: FunctionSite) -> tuple[Mutation | None, object, str]:
    """Returns (mutation or None, model turn, rejection reason). One retry if the rewrite is identical."""
    messages = [{"role": "user", "content": f"```python\n{site.source}\n```"}]
    turn = model.complete(REWRITE_SYSTEM, messages, [])
    mutation, why = _check(files, site, turn.text)
    if why == "no behavioural change":
        messages += [{"role": "assistant", "text": turn.text, "tool_calls": [], "raw": turn.raw},
                     {"role": "user", "content": RETRY_IDENTICAL}]
        first_usage = turn.usage
        turn = model.complete(REWRITE_SYSTEM, messages, [])
        turn.usage = first_usage + turn.usage  # cost accounting covers both calls
        mutation, why = _check(files, site, turn.text)
    return mutation, turn, why


def _check(files: dict[str, str], site: FunctionSite, text: str) -> tuple[Mutation | None, str]:
    turn_text = text
    code = _extract_code(turn_text)
    if not code:
        return None, "no code block"
    # Models return methods either flush-left or already indented: normalise before parsing and re-indenting.
    code = textwrap.dedent(code)
    try:
        new_fn = ast.parse(code).body[0]
    except (SyntaxError, IndexError):
        return None, "does not parse"
    if not isinstance(new_fn, ast.FunctionDef) or new_fn.name != site.name or \
            ast.dump(new_fn.args) != ast.dump(site.node.args):
        return None, "signature changed"
    if HINT_WORDS.search(code):
        return None, "hinting comment"
    src = files[site.path]
    lines = src.splitlines(keepends=True)
    indent = lines[site.node.lineno - 1][: site.node.col_offset]
    body = "".join((indent + ln if ln.strip() else ln) for ln in code.rstrip("\n").splitlines(keepends=True)) + "\n"
    new_src = "".join(lines[: site.node.lineno - 1]) + body + "".join(lines[site.node.end_lineno:])
    try:
        if ast.dump(ast.parse(new_src)) == ast.dump(ast.parse(src)):
            return None, "no behavioural change"
    except SyntaxError:
        return None, "spliced file does not parse"
    old_lines, new_lines = src.splitlines(), new_src.splitlines()
    changed = sum(1 for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes()
                  if tag != "equal" for _ in range(max(i2 - i1, j2 - j1)))
    if changed > MAX_CHANGED_LINES:
        return None, f"too many changed lines ({changed}); a subtle bug should be small"
    i = next((k for k, (a, b) in enumerate(zip(old_lines, new_lines, strict=False)) if a != b), site.node.lineno - 1)
    return Mutation("llm_rewrite", site.path, i + 1, site.name, old_lines[i] if i < len(old_lines) else "",
                    new_lines[i] if i < len(new_lines) else "", new_src), ""


def pick_sites(files: dict[str, str], rng: random.Random, k: int) -> list[FunctionSite]:
    sites = function_sites(files)
    rng.shuffle(sites)
    return sites[:k]
