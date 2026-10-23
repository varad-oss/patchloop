"""Validate candidate bugs in a long-lived, isolated container per repository.

A candidate is accepted when:
  - the original repo passes (baseline, run twice; tests that are not stable-passing are dropped),
  - the mutated repo fails at least one baseline test (FAIL_TO_PASS) and every other baseline test
    still passes (PASS_TO_PASS),
  - both mutated runs agree exactly (no flaky outcomes),
  - its diff is not a duplicate of an accepted one.
"""

from __future__ import annotations

import hashlib
import shlex
from dataclasses import dataclass

from ..pytest_results import RESULT_FLAGS, parse_outcomes, passed
from ..sandbox.docker_env import DockerEnv

MAX_FAIL_FRACTION = 0.25  # reject bugs that break a quarter of the suite (usually an import-time crash)


@dataclass
class Validated:
    bug_patch: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    failure_output: str


class Workbench:
    def __init__(self, image: str, tests_dir: str, test_cmd: str):
        self.env = DockerEnv(image, tests_dir)
        self.test_cmd = test_cmd
        self.baseline: set[str] = set()
        self.seen: set[str] = set()

    def __enter__(self) -> Workbench:
        self.env.start()
        a, b = self.run_suite(), self.run_suite()
        self.baseline = passed(a) & passed(b)
        if not self.baseline:
            raise RuntimeError("baseline: no passing tests - check the image and test command")
        return self

    def __exit__(self, *exc) -> None:
        self.env.close()

    def run_suite(self, selector: str = "") -> dict[str, str]:
        r = self.env.exec(f"{self.test_cmd} {selector} {RESULT_FLAGS}", 300)
        return parse_outcomes(r.output)

    def read(self, path: str) -> str:
        content, err = self.env.read_file(path)
        if content is None:
            raise FileNotFoundError(f"{path}: {err}")
        return content

    def list_sources(self, source_dirs: list[str]) -> list[str]:
        dirs = " ".join(shlex.quote(d) for d in source_dirs)
        r = self.env.exec(f"git ls-files -- {dirs} | grep '\\.py$'", 30)
        tests = self.env.tests_dir + "/"
        return [p for p in r.output.split() if not p.startswith(tests) and "/tests/" not in p
                and not p.split("/")[-1].startswith("test_") and p.split("/")[-1] != "conftest.py"]

    def try_candidate(self, path: str, new_source: str) -> Validated | None:
        original = self.read(path)
        try:
            if self.env.write_file(path, new_source).exit_code != 0:
                return None
            patch = self.env.exec(f"git diff -- {shlex.quote(path)}", 30).output
            key = hashlib.sha256(patch.encode()).hexdigest()
            if not patch.strip() or key in self.seen:
                return None
            first, second = self.run_suite(), self.run_suite()
            if first != second:
                return None
            still = passed(first) & self.baseline
            f2p = sorted(self.baseline - still)
            if not f2p or len(f2p) > MAX_FAIL_FRACTION * len(self.baseline):
                return None
            selector = " ".join(shlex.quote(t) for t in f2p[:5])
            failure = self.env.exec(f"python -m pytest -p no:cacheprovider -q --tb=short --color=no {selector}",
                                    120).output
            self.seen.add(key)
            return Validated(patch, f2p, sorted(still), failure)
        finally:
            self.env.write_file(path, original)
