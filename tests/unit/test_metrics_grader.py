import pytest

from patchloop.evals.grader import forbidden_paths, grade, touched_files
from patchloop.evals.metrics import classify_failure, pass_at_k, pass_hat_k, wilson


def test_wilson_hand_computed():
    # 15/30: p=0.5, z=1.96 -> centre 0.5, half-width = 1.96*sqrt(0.25/30 + 1.96^2/3600)/(1+1.96^2/30)
    lo, hi = wilson(15, 30)
    assert lo == pytest.approx(0.3315, abs=1e-3) and hi == pytest.approx(0.6685, abs=1e-3)
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    assert wilson(10, 10)[1] == pytest.approx(1.0)
    assert wilson(0, 0) == (0.0, 0.0)


def test_pass_at_k_hand_computed():
    # n=3, c=1: pass@1 = 1/3; pass@2 = 1 - C(2,2)/C(3,2) = 2/3; pass@3 = 1
    assert pass_at_k(3, 1, 1) == pytest.approx(1 / 3)
    assert pass_at_k(3, 1, 2) == pytest.approx(2 / 3)
    assert pass_at_k(3, 1, 3) == 1.0
    assert pass_at_k(3, 0, 3) == 0.0
    # n=5, c=2, k=2: 1 - C(3,2)/C(5,2) = 1 - 3/10
    assert pass_at_k(5, 2, 2) == pytest.approx(0.7)


def test_pass_hat_k_hand_computed():
    # n=3, c=2: pass^1 = 2/3, pass^2 = C(2,2)/C(3,2) = 1/3, pass^3 = 0
    assert pass_hat_k(3, 2, 1) == pytest.approx(2 / 3)
    assert pass_hat_k(3, 2, 2) == pytest.approx(1 / 3)
    assert pass_hat_k(3, 2, 3) == 0.0
    assert pass_hat_k(3, 3, 3) == 1.0
    with pytest.raises(ValueError):
        pass_hat_k(2, 1, 3)


PATCH = """diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1 +1 @@
-a
+b
diff --git a/conftest.py b/conftest.py
new file mode 100644
"""


def test_touched_and_forbidden():
    assert touched_files(PATCH) == ["pkg/mod.py", "conftest.py"]
    assert forbidden_paths(PATCH, "tests") == ["conftest.py"]
    assert forbidden_paths("diff --git a/tests/test_x.py b/tests/test_x.py\n", "tests") == ["tests/test_x.py"]
    assert forbidden_paths("diff --git a/pkg/a.py b/pkg/a.py\n", "tests") == []


def test_grader_short_circuits_without_docker():
    task = {"tests_dir": "tests", "image": "x", "bug_patch": ""}
    assert grade(task, "")["reason"] == "empty_patch"
    g = grade(task, PATCH, env_factory=lambda *a: pytest.fail("must not start a container"))
    assert g["tampered"] and g["reason"] == "touches_tests" and not g["resolved"]


def _ep(**kw):
    base = {"stop_reason": "submitted", "grade": {"reason": "fail_to_pass_still_failing", "touched": ["pkg/mod.py"]},
            "tool_calls": 10, "tool_errors": 1}
    base.update(kw)
    return base


TASK = {"tests_dir": "tests", "difficulty": {"file": "pkg/mod.py"}}


def test_failure_classes():
    assert classify_failure(_ep(stop_reason="error"), TASK, []) == "infrastructure_error"
    assert classify_failure(_ep(grade={"tampered": True}), TASK, []) == "tamper_attempt"
    traj = [{"tool_calls": [{"name": "str_replace", "args": {"path": "tests/test_x.py"}}]}]
    assert classify_failure(_ep(), TASK, traj) == "tamper_attempt"
    assert classify_failure(_ep(stop_reason="step_limit"), TASK, []) == "budget_exhausted"
    assert classify_failure(_ep(tool_errors=6), TASK, []) == "tool_misuse"
    assert classify_failure(_ep(grade={"touched": ["other.py"]}), TASK, []) == "never_found_the_bug"
    assert classify_failure(_ep(grade={"touched": ["pkg/mod.py"], "reason": "broke_pass_to_pass"}), TASK, []) == "broke_other_tests"
    assert classify_failure(_ep(), TASK, []) == "wrong_fix"


def test_mcnemar_exact_hand_computed():
    from patchloop.evals.report import mcnemar_exact

    # 11 vs 2 discordant: 2 * sum_{k<=2} C(13,k) / 2^13 = 2 * (1 + 13 + 78) / 8192
    assert mcnemar_exact(11, 2) == pytest.approx(2 * 92 / 8192)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(3, 3) == 1.0
