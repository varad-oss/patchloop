"""Grade a submitted patch in a FRESH container: bug applied, agent's diff applied, full suite run.

Resolved = the diff applies, touches no test or test-configuration file, every FAIL_TO_PASS test
passes and every PASS_TO_PASS test still passes.
"""

from __future__ import annotations

import re

from ..pytest_results import RESULT_FLAGS, parse_outcomes, passed
from ..sandbox.base import SandboxError
from ..sandbox.docker_env import DockerEnv

# Files that can change test outcomes without fixing anything.
FORBIDDEN_BASENAMES = {"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "setup.py",
                       "noxfile.py", "sitecustomize.py", "usercustomize.py"}


def touched_files(patch: str) -> list[str]:
    files = []
    for a, b in re.findall(r"^diff --git a/(\S+) b/(\S+)$", patch, re.M):
        for p in (a, b):
            if p not in files:
                files.append(p)
    return files


def forbidden_paths(patch: str, tests_dir: str) -> list[str]:
    bad = []
    for p in touched_files(patch):
        base = p.rsplit("/", 1)[-1]
        if p.startswith(tests_dir.rstrip("/") + "/") or base in FORBIDDEN_BASENAMES or base.endswith(".pth"):
            bad.append(p)
    return bad


def grade(task: dict, patch: str, env_factory=DockerEnv) -> dict:
    result = {"resolved": False, "reason": "", "tampered": False, "applied": False,
              "f2p_failed": [], "p2p_failed": [], "touched": touched_files(patch)}
    if not patch.strip():
        result["reason"] = "empty_patch"
        return result
    bad = forbidden_paths(patch, task["tests_dir"])
    if bad:
        result.update(reason="touches_tests", tampered=True, forbidden=bad)
        return result
    try:
        with env_factory(task["image"], task["tests_dir"], task["bug_patch"]) as env:
            env.write_file("/tmp/model.patch", patch)
            r = env.exec("git apply --whitespace=nowarn /tmp/model.patch", 60)
            if r.exit_code != 0:
                result["reason"] = "patch_does_not_apply"
                result["apply_output"] = r.output[-1000:]
                return result
            result["applied"] = True
            outcomes = parse_outcomes(env.exec(f"{task['test_cmd']} {RESULT_FLAGS}", 600).output)
    except SandboxError as e:
        result["reason"] = f"infrastructure: {e}"
        return result
    ok = passed(outcomes)
    result["f2p_failed"] = [t for t in task["FAIL_TO_PASS"] if t not in ok]
    result["p2p_failed"] = [t for t in task["PASS_TO_PASS"] if t not in ok]
    result["resolved"] = not result["f2p_failed"] and not result["p2p_failed"]
    result["reason"] = "resolved" if result["resolved"] else (
        "fail_to_pass_still_failing" if result["f2p_failed"] else "broke_pass_to_pass")
    return result
