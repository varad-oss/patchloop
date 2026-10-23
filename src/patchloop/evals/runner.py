"""Run episodes in parallel, resumably, and grade each one in a fresh container.

results/<run_id>/
  config.json                    model, toolset, budget, task ids, trials
  episodes/<id>__t<k>.json       one record per episode (agent result + grade); presence = done
  trajectories/<id>__t<k>.jsonl  step-by-step trajectory
  summary.json                   aggregate metrics (written by `patchloop report`)
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from ..agent.loop import Budget, run_episode
from ..agent.models import FakeModel, ModelAdapter, load_pricing, make_adapter
from ..agent.tools import Toolbox
from ..agent.trajectory import Trajectory, read_trajectory
from ..config import RESULTS_DIR
from ..sandbox.base import SandboxError
from ..sandbox.docker_env import DockerEnv
from .grader import grade
from .metrics import classify_failure


def oracle_model(task: dict) -> FakeModel:
    """Applies the reverse of the bug patch. Must resolve 100% - a sanity check of the harness."""
    cmd = f"cat > /tmp/fix.patch <<'PATCHLOOP_EOF'\n{task['bug_patch']}PATCHLOOP_EOF\ngit apply -R /tmp/fix.patch"
    return FakeModel([{"calls": [("bash", {"command": cmd})]}, {"calls": [("bash", {"command": task["test_cmd"] + " -q | tail -1"})]},
                      {"calls": [("submit", {"summary": "oracle: reverted the injected bug"})]}])


def giveup_model(task: dict) -> FakeModel:
    """Runs the tests once and submits nothing - exercises the unresolved path."""
    return FakeModel([{"calls": [("run_tests", {})]}, {"calls": [("submit", {"summary": "fake: no fix"})]}])


def model_for(spec: str, task: dict, effort: str) -> ModelAdapter:
    if spec == "oracle":
        return oracle_model(task)
    if spec == "fake":
        return giveup_model(task)
    return make_adapter(spec, effort)


def episode_key(task: dict, trial: int) -> str:
    return f"{task['instance_id']}__t{trial}"


def run_one(task: dict, spec: str, toolset: str, budget: Budget, run_dir: Path, trial: int,
            effort: str = "low") -> dict:
    key = episode_key(task, trial)
    traj_path = run_dir / "trajectories" / f"{key}.jsonl"
    traj = Trajectory(traj_path)
    record: dict = {"instance_id": task["instance_id"], "trial": trial, "model": spec, "toolset": toolset}
    t0 = time.monotonic()
    try:
        with DockerEnv(task["image"], task["tests_dir"], task["bug_patch"]) as env:
            before = env.tests_hash()
            model = model_for(spec, task, effort)
            result = run_episode(task["problem_statement"], task["test_cmd"], model,
                                 Toolbox(env, task["test_cmd"], toolset), budget, traj)
            patch = env.diff()
            tampered = env.tests_hash() != before
        record.update(result.to_dict())
        record.update(patch=patch, tampered=tampered)
        g = grade(task, patch)
        if tampered:
            g.update(resolved=False, tampered=True, reason="tests_changed_during_episode")
    except (SandboxError, OSError) as e:
        record.update(stop_reason="error", steps=0, cost_usd=0.0, wall_s=0.0, compactions=0, tool_calls=0,
                      tool_errors=0, usage={k: 0 for k in ("input_tokens", "output_tokens", "thinking_tokens",
                                                            "cache_read_tokens", "cache_write_tokens")},
                      error=f"{type(e).__name__}: {e}", patch="", tampered=False)
        g = {"resolved": False, "reason": f"infrastructure: {e}", "touched": [], "tampered": False}
    record["grade"] = g
    record["episode_wall_s"] = round(time.monotonic() - t0, 2)
    traj_records = read_trajectory(traj_path) if traj_path.exists() else []
    record["failure_class"] = None if g["resolved"] else classify_failure(record, task, traj_records)
    out = run_dir / "episodes" / f"{key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, default=str))
    return record


def run_experiment(run_id: str, tasks: list[dict], spec: str, toolset: str = "structured", trials: int = 1,
                   budget: Budget | None = None, concurrency: int = 4, effort: str = "low", log=print) -> list[dict]:
    budget = budget or Budget()
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = run_dir / "config.json"
    cfg = {"run_id": run_id, "model": spec, "toolset": toolset, "trials": trials, "effort": effort,
           "budget": asdict(budget), "pricing_checked": load_pricing().get("checked"),
           "tasks": sorted({t["instance_id"] for t in tasks} |
                           set(json.loads(cfg_path.read_text())["tasks"] if cfg_path.exists() else []))}
    cfg_path.write_text(json.dumps(cfg, indent=2))
    jobs = [(t, k) for t in tasks for k in range(1, trials + 1)
            if not (run_dir / "episodes" / f"{episode_key(t, k)}.json").exists()]
    log(f"{run_id}: {len(jobs)} episodes to run ({len(tasks) * trials - len(jobs)} already done)")
    done: list[dict] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_one, t, spec, toolset, budget, run_dir, k, effort): (t, k) for t, k in jobs}
        for f in as_completed(futures):
            t, k = futures[f]
            try:
                rec = f.result()
            except Exception:  # never lose the rest of a run to one crash
                log(f"  {episode_key(t, k)} crashed:\n{traceback.format_exc()}")
                continue
            with lock:
                done.append(rec)
            log(f"  {episode_key(t, k)}: {rec['stop_reason']}, resolved={rec['grade']['resolved']}, "
                f"steps={rec['steps']}, ${rec['cost_usd']:.4f}")
    return done


def load_episodes(run_id: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((RESULTS_DIR / run_id / "episodes").glob("*.json"))]
