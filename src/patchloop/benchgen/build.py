"""Benchmark build pipeline: candidates -> validation -> bug report -> leak check -> task JSON."""

from __future__ import annotations

import json
import random
from pathlib import Path

from ..agent.models import ModelAdapter, cost_usd
from ..config import TASKS_DIR, repos
from . import issues, llm_rewrite, mutators
from .validate import Workbench


def difficulty(m: mutators.Mutation, strategy: str, f2p: list[str], patch: str) -> dict:
    changed = sum(1 for ln in patch.splitlines() if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")))
    named = bool(m.function) and any(m.function.lower() in t.split("::")[-1].lower() for t in f2p)
    return {"strategy": strategy, "mutation": m.op, "n_fail": len(f2p), "lines_changed": changed,
            "func_named_in_test": named, "file": m.path, "function": m.function}


def make_task(repo_name: str, cfg: dict, m: mutators.Mutation, v, strategy: str,
              issue_model: ModelAdapter | None, log=print) -> tuple[dict | None, float]:
    excerpt = issues.failure_excerpt(v.failure_output, cfg["tests_dir"])
    cost = 0.0
    if issue_model is not None:
        text, turn = issues.llm_issue(issue_model, v.fail_to_pass, excerpt)
        cost = cost_usd(issue_model.model, turn.usage)
    else:
        text = issues.template_issue(v.fail_to_pass, excerpt)
    leaks = issues.leak_check(text, m.path, m.lineno, m.original_line, m.mutated_line)
    if leaks:
        log(f"  rejected by leak check: {leaks}")
        return None, cost
    fn = (m.function or "module").lower()
    task = {
        "instance_id": "",  # filled by caller
        "repo": repo_name,
        "base_commit": cfg["commit"],
        "image": cfg["image"],
        "tests_dir": cfg["tests_dir"],
        "test_cmd": cfg["test_cmd"],
        "bug_patch": v.bug_patch,
        "problem_statement": text,
        "issue_writer": "llm:" + issue_model.model if issue_model else "template",
        "FAIL_TO_PASS": v.fail_to_pass,
        "PASS_TO_PASS": v.pass_to_pass,
        "difficulty": difficulty(m, strategy, v.fail_to_pass, v.bug_patch),
        "_slug": f"{fn}-{m.op}",
    }
    return task, cost


def build(repo_name: str, target: int, *, seed: int = 0, strategy: str = "ast",
          issue_model: ModelAdapter | None = None, rewrite_model: ModelAdapter | None = None,
          out_dir: Path = TASKS_DIR, max_attempts: int = 400, log=print) -> list[dict]:
    cfg = repos()[repo_name]
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    accepted: list[dict] = []
    spent = 0.0
    with Workbench(cfg["image"], cfg["tests_dir"], cfg["test_cmd"]) as wb:
        files = {p: wb.read(p) for p in wb.list_sources(cfg["source_dirs"])}
        log(f"{repo_name}: {len(files)} source files, {len(wb.baseline)} baseline-passing tests")
        if strategy == "ast":
            # Round-robin over mutation operators so the benchmark is not dominated by one kind of bug.
            pools = {op: mutators.sample(files, op, rng, 10_000) for op in mutators.MUTATORS}
            queue = []
            while any(pools.values()):
                for op in mutators.MUTATORS:
                    if pools[op]:
                        queue.append(pools[op].pop())
        else:
            queue = llm_rewrite.pick_sites(files, rng, max_attempts)
        per_function: dict[str, int] = {}
        for attempt, item in enumerate(queue[:max_attempts]):
            if len(accepted) >= target:
                break
            if strategy == "llm":
                m, turn, why = llm_rewrite.rewrite(rewrite_model, files, item)
                spent += cost_usd(rewrite_model.model, turn.usage)
                if m is None:
                    log(f"[{attempt}] llm rewrite of {item.name} rejected: {why}")
                    continue
            else:
                m = item
            key = f"{m.path}:{m.function}"
            if per_function.get(key, 0) >= 1:  # at most one bug per function -> diverse tasks
                continue
            v = wb.try_candidate(m.path, m.new_source)
            if v is None:
                continue
            task, c = make_task(repo_name, cfg, m, v, "llm_rewrite" if strategy == "llm" else "ast", issue_model, log)
            spent += c
            if task is None:
                continue
            per_function[key] = 1
            slug = task.pop("_slug")
            task["instance_id"] = f"{repo_name}__{slug}-{len(accepted) + 1:03d}"
            (out_dir / f"{task['instance_id']}.json").write_text(json.dumps(task, indent=2))
            accepted.append(task)
            log(f"[{attempt}] accepted {task['instance_id']} ({len(v.fail_to_pass)} failing tests)")
    log(f"{repo_name}: {len(accepted)} tasks accepted; API spend ${spent:.4f}")
    return accepted
