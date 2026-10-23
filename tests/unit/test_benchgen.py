import ast
import random

import pytest

from patchloop.benchgen import issues, mutators
from patchloop.pytest_results import parse_outcomes, passed

SRC = '''
def f(xs, lo=0, flag=True):
    if not xs:
        return None
    out = []
    for i in range(len(xs)):
        if xs[i] < lo and flag:
            out.append(max(xs[i], lo))
    return out[1:3]
'''


@pytest.mark.parametrize("op", list(mutators.MUTATORS))
def test_each_mutator_changes_exactly_one_site(op):
    cands = list(mutators.candidates("pkg/m.py", SRC, op))
    assert cands, f"no candidates for {op}"
    for m in cands:
        ast.parse(m.new_source)
        old, new = SRC.splitlines(), m.new_source.splitlines()
        if op == "remove_guard":  # the guard's lines collapse into one `pass`
            assert len(new) < len(old) and "pass" in new[m.lineno - 1]
            continue
        assert len(old) == len(new)
        assert sum(a != b for a, b in zip(old, new, strict=True)) == 1
        assert m.function == "f" and m.op == op


def test_compare_flip_example():
    lines = {m.mutated_line.strip() for m in mutators.candidates("m.py", SRC, "compare_flip")}
    assert "if xs[i] <= lo and flag:" in lines


def test_sample_is_seeded():
    files = {"m.py": SRC}
    a = mutators.sample(files, "off_by_one", random.Random(1), 3)
    b = mutators.sample(files, "off_by_one", random.Random(1), 3)
    assert [m.new_source for m in a] == [m.new_source for m in b]


def test_parse_outcomes():
    out = ("PASSED tests/t.py::test_a\nFAILED tests/t.py::test_b - AssertionError: x\n"
           "ERROR tests/t.py::test_c - Exception\nSKIPPED [1] tests/t.py:3: reason\nPASSED tests/t.py::test_d[1-2]\n")
    o = parse_outcomes(out)
    assert o == {"tests/t.py::test_a": "PASSED", "tests/t.py::test_b": "FAILED",
                 "tests/t.py::test_c": "ERROR", "tests/t.py::test_d[1-2]": "PASSED"}
    assert passed(o) == {"tests/t.py::test_a", "tests/t.py::test_d[1-2]"}


TB = """____ test_median_even ____
tests/test_stats.py:18: in test_median_even
    assert median([4, 1, 3, 2]) == 2.5
toyrepo/stats.py:17: in median
    return (ordered[mid] + ordered[mid + 1]) / 2
E   assert 3.5 == 2.5
"""


def test_failure_excerpt_drops_library_frames():
    ex = issues.failure_excerpt(TB, "tests")
    assert "test_median_even" in ex and "E   assert 3.5 == 2.5" in ex
    assert "toyrepo/stats.py" not in ex and "ordered[mid + 1]" not in ex and ":18" not in ex


def test_leak_check():
    clean = issues.template_issue(["tests/test_stats.py::test_median_even"], issues.failure_excerpt(TB, "tests"))
    assert issues.leak_check(clean, "toyrepo/stats.py", 17, "return (ordered[mid - 1] + ordered[mid]) / 2",
                             "return (ordered[mid] + ordered[mid + 1]) / 2") == []
    assert issues.leak_check("bug in toyrepo/stats.py", "toyrepo/stats.py", 17, "", "")
    assert issues.leak_check("see stats.py", "toyrepo/stats.py", 17, "", "")
    assert issues.leak_check("broken at line 17", "toyrepo/stats.py", 17, "", "")
    assert issues.leak_check("it does (ordered[mid] + ordered[mid + 1]) / 2", "x/y.py", 9, "",
                             "return (ordered[mid] + ordered[mid + 1]) / 2") == []  # partial quote is fine
    assert issues.leak_check("it does return (ordered[mid] + ordered[mid + 1]) / 2", "x/y.py", 9, "",
                             "return (ordered[mid] + ordered[mid + 1]) / 2")
    assert issues.leak_check("test_stats.py fails", "toyrepo/stats.py", 17, "", "") == []
