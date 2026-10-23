"""Strategy A: syntax-tree mutations that inject one realistic bug at one site.

Each mutator finds candidate nodes with `ast`, builds a mutated copy of ONE node, and splices
`ast.unparse(new_node)` back over the original node's exact source span. Only single-line
nodes are mutated, so formatting elsewhere is untouched and the diff is one line.
"""

from __future__ import annotations

import ast
import copy
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass

COMPARE_FLIPS = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq,
                 ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}


@dataclass
class Mutation:
    op: str
    path: str
    lineno: int
    function: str | None
    original_line: str
    mutated_line: str
    new_source: str


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _enclosing_function(node: ast.AST, parents: dict) -> str | None:
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return node.name
    return None


def _single_line(node: ast.AST) -> bool:
    return getattr(node, "lineno", None) is not None and node.lineno == node.end_lineno


def _in_function(node: ast.AST, parents: dict) -> bool:
    return _enclosing_function(node, parents) is not None


# ------------------------------------------------------------------- mutators
# Each yields (target_node, replacement_node_or_None). None means "delete this statement".


def m_compare_flip(tree, parents):
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in COMPARE_FLIPS:
            new = copy.deepcopy(n)
            new.ops = [COMPARE_FLIPS[type(n.ops[0])]()]
            yield n, new


def m_off_by_one(tree, parents):
    for n in ast.walk(tree):
        is_range = isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "range"
        if is_range:
            for i, arg in enumerate(n.args):
                new = copy.deepcopy(n)
                new.args[i] = ast.BinOp(copy.deepcopy(arg), ast.Add(), ast.Constant(1)) \
                    if not isinstance(arg, ast.Constant) else ast.Constant(arg.value + 1)
                yield n, new
        if isinstance(n, ast.Slice):
            for attr in ("lower", "upper"):
                bound = getattr(n, attr)
                if bound is None:
                    continue
                new = copy.deepcopy(n)
                if isinstance(bound, ast.Constant) and isinstance(bound.value, int):
                    setattr(new, attr, ast.Constant(bound.value + 1))
                else:
                    setattr(new, attr, ast.BinOp(copy.deepcopy(bound), ast.Sub(), ast.Constant(1)))
                yield n, new


def m_negate_condition(tree, parents):
    for n in ast.walk(tree):
        if isinstance(n, ast.If | ast.While) and not isinstance(n.test, ast.UnaryOp):
            yield n.test, ast.UnaryOp(ast.Not(), copy.deepcopy(n.test))


def m_swap_args(tree, parents):
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and len(n.args) == 2 and not n.keywords
                and not any(isinstance(a, ast.Starred) for a in n.args)
                and ast.dump(n.args[0]) != ast.dump(n.args[1])):
            new = copy.deepcopy(n)
            new.args = [new.args[1], new.args[0]]
            yield n, new


def m_remove_guard(tree, parents):
    for n in ast.walk(tree):
        for field in ("body", "orelse"):
            block = getattr(n, field, None)
            if not isinstance(block, list) or len(block) < 2:
                continue
            for stmt in block:
                if (isinstance(stmt, ast.If) and not stmt.orelse and len(stmt.body) == 1
                        and isinstance(stmt.body[0], ast.Return | ast.Raise | ast.Continue | ast.Break)):
                    yield stmt, None


def m_change_constant(tree, parents):
    for n in ast.walk(tree):
        values: list[ast.expr] = []
        if isinstance(n, ast.Return) and n.value is not None:
            values = [n.value]
        elif isinstance(n, ast.arguments):
            values = [d for d in [*n.defaults, *n.kw_defaults] if d is not None]
        for v in values:
            if not isinstance(v, ast.Constant):
                continue
            if isinstance(v.value, bool):
                yield v, ast.Constant(not v.value)
            elif isinstance(v.value, int):
                yield v, ast.Constant(v.value + 1)


def m_bool_op_swap(tree, parents):
    for n in ast.walk(tree):
        if isinstance(n, ast.BoolOp):
            new = copy.deepcopy(n)
            new.op = ast.Or() if isinstance(n.op, ast.And) else ast.And()
            yield n, new


MUTATORS: dict[str, Callable] = {
    "compare_flip": m_compare_flip,
    "off_by_one": m_off_by_one,
    "negate_condition": m_negate_condition,
    "swap_args": m_swap_args,
    "remove_guard": m_remove_guard,
    "change_constant": m_change_constant,
    "bool_op_swap": m_bool_op_swap,
}


def _splice(source: str, node: ast.AST, replacement: ast.AST | None) -> str | None:
    lines = source.splitlines(keepends=True)
    if replacement is None:  # delete whole statement lines
        start, end = node.lineno - 1, node.end_lineno
        indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
        return "".join(lines[:start] + [indent + "pass\n"] + lines[end:])
    if not _single_line(node):
        return None
    line = lines[node.lineno - 1]
    # col offsets are UTF-8 byte offsets
    raw = line.encode()
    new_line = (raw[: node.col_offset] + ast.unparse(replacement).encode() + raw[node.end_col_offset:]).decode()
    return "".join(lines[: node.lineno - 1] + [new_line] + lines[node.lineno:])


def candidates(path: str, source: str, op: str) -> Iterator[Mutation]:
    tree = ast.parse(source)
    parents = _parents(tree)
    lines = source.splitlines()
    for node, replacement in MUTATORS[op](tree, parents):
        if not _in_function(node, parents):
            continue
        if replacement is None and node.end_lineno - node.lineno > 3:
            continue
        new_source = _splice(source, node, replacement)
        if new_source is None or new_source == source:
            continue
        try:
            new_tree = ast.parse(new_source)
        except SyntaxError:
            continue
        if ast.dump(new_tree) == ast.dump(tree):
            continue
        new_lines = new_source.splitlines()
        changed = [i for i, (a, b) in enumerate(zip(lines, new_lines, strict=False)) if a != b]
        if not changed:
            continue
        i = changed[0]
        yield Mutation(op, path, i + 1, _enclosing_function(node, parents), lines[i], new_lines[i], new_source)


def sample(files: dict[str, str], op: str, rng: random.Random, k: int) -> list[Mutation]:
    """Up to k random candidates for `op` across all files."""
    pool = [m for path, src in sorted(files.items()) for m in candidates(path, src, op)]
    rng.shuffle(pool)
    return pool[:k]
