"""Strategy B (in the spirit of SWE-smith): a model reimplements one function with one subtle bug.

Opt-in: costs API money, so `patchloop bench --strategy llm` refuses to run without --yes.
Checks before validation: same signature, parses, no hinting comments, actually different.
"""

from __future__ import annotations

import ast
import random
import re
from dataclasses import dataclass

from ..agent.models import ModelAdapter
from .mutators import Mutation

REWRITE_SYSTEM = """You help build a benchmark for debugging agents. You will be given one Python function.
Rewrite it so that it keeps the exact same signature and almost the same behaviour, but contains ONE
subtle, realistic bug of the kind a careful developer might write (wrong boundary, missed edge case,
wrong variable, inverted condition, wrong default). Rules: same name and parameters; do not add or
change comments or docstrings; no comments hinting at the bug; keep the style of the original.
Reply with only the rewritten function in a single ```python code block."""

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
    """Returns (mutation or None, model turn, rejection reason)."""
    turn = model.complete(REWRITE_SYSTEM, [{"role": "user", "content": f"```python\n{site.source}\n```"}], [])
    code = _extract_code(turn.text)
    if not code:
        return None, turn, "no code block"
    try:
        new_fn = ast.parse(code).body[0]
    except (SyntaxError, IndexError):
        return None, turn, "does not parse"
    if not isinstance(new_fn, ast.FunctionDef) or new_fn.name != site.name or \
            ast.dump(new_fn.args) != ast.dump(site.node.args):
        return None, turn, "signature changed"
    if HINT_WORDS.search(code):
        return None, turn, "hinting comment"
    src = files[site.path]
    lines = src.splitlines(keepends=True)
    indent = lines[site.node.lineno - 1][: site.node.col_offset]
    body = "".join((indent + ln if ln.strip() else ln) for ln in code.rstrip("\n").splitlines(keepends=True)) + "\n"
    new_src = "".join(lines[: site.node.lineno - 1]) + body + "".join(lines[site.node.end_lineno:])
    try:
        if ast.dump(ast.parse(new_src)) == ast.dump(ast.parse(src)):
            return None, turn, "no behavioural change"
    except SyntaxError:
        return None, turn, "spliced file does not parse"
    old_lines, new_lines = src.splitlines(), new_src.splitlines()
    i = next((k for k, (a, b) in enumerate(zip(old_lines, new_lines, strict=False)) if a != b), site.node.lineno - 1)
    return Mutation("llm_rewrite", site.path, i + 1, site.name, old_lines[i] if i < len(old_lines) else "",
                    new_lines[i] if i < len(new_lines) else "", new_src), turn, ""


def pick_sites(files: dict[str, str], rng: random.Random, k: int) -> list[FunctionSite]:
    sites = function_sites(files)
    rng.shuffle(sites)
    return sites[:k]
