"""patchloop command line. `patchloop <command> --help` for options."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from .config import RESULTS_DIR, ROOT, TASKS_DIR, load_tasks

PILOT_TASKS = 3


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def _is_paid(model: str) -> bool:
    from .agent.models import load_pricing

    if model in ("fake", "oracle") or model.startswith("ollama:"):
        return False
    table = load_pricing()["models"].get(model)
    return table is None and not model.startswith("openai:") or bool(table and table["input"] > 0)


def cmd_demo(args) -> int:
    """FakeModel fixes the toy bug inside Docker. No API key needed."""
    from .agent.loop import run_episode
    from .agent.models import FakeModel
    from .agent.tools import Toolbox
    from .agent.trajectory import Trajectory
    from .evals.grader import grade
    from .sandbox.docker_env import DockerEnv
    from .sandbox.local_env import TOY_REPO, UnsafeLocalEnv

    task = json.loads((ROOT / "bench" / "toy" / "toy__median-even.json").read_text())
    script = [
        {"text": "Reproduce first.", "calls": [("run_tests", {})]},
        {"text": "Find median.", "calls": [("search", {"pattern": "def median"})]},
        {"text": "Read it.", "calls": [("view_file", {"path": "toyrepo/stats.py", "start_line": 10, "end_line": 20})]},
        {"text": "The even case averages the wrong pair: it should use mid-1 and mid.",
         "calls": [("str_replace", {"path": "toyrepo/stats.py", "old_str": "(ordered[mid] + ordered[mid + 1])",
                                    "new_str": "(ordered[mid - 1] + ordered[mid])"})]},
        {"text": "Verify.", "calls": [("run_tests", {})]},
        {"text": "Done.", "calls": [("submit", {"summary": "median() averaged ordered[mid] and ordered[mid+1] "
                                                           "for even lengths; it must average mid-1 and mid."})]},
    ]
    traj_path = RESULTS_DIR / "demo" / "trajectory.jsonl"
    if args.unsafe_local:
        env = UnsafeLocalEnv(TOY_REPO, task["tests_dir"], task["bug_patch"], unsafe_local=True)
    else:
        env = DockerEnv(task["image"], task["tests_dir"], task["bug_patch"])
    with env:
        result = run_episode(task["problem_statement"], task["test_cmd"], FakeModel(script),
                             Toolbox(env, task["test_cmd"]), traj=Trajectory(traj_path))
        patch = env.diff()
    print(f"stop_reason={result.stop_reason} steps={result.steps}\n{patch}")
    if not args.unsafe_local:
        g = grade(task, patch)
        print(f"grader: resolved={g['resolved']} ({g['reason']})")
    print(f"trajectory: {traj_path}")
    return 0


def cmd_bench(args) -> int:
    from .agent.models import make_adapter
    from .benchgen.build import build

    _load_env()
    if (args.issues == "llm" or args.strategy == "llm") and not args.yes:
        print("LLM issue writing / rewriting costs API money. Re-run with --yes after approving.")
        return 2
    issue_model = make_adapter(args.model, "low") if args.issues == "llm" else None
    rewrite_model = make_adapter(args.model, "low") if args.strategy == "llm" else None
    build(args.repo, args.target, seed=args.seed, strategy=args.strategy, issue_model=issue_model,
          rewrite_model=rewrite_model, max_attempts=args.max_attempts)
    return 0


def _select_tasks(args) -> list[dict]:
    tasks = load_tasks(Path(args.tasks_dir), args.task)
    if args.include_toy:
        tasks = load_tasks(ROOT / "bench" / "toy") + tasks
    if args.limit:
        tasks = tasks[: args.limit]
    return tasks


def cmd_eval(args) -> int:
    from .agent.loop import Budget
    from .evals.runner import load_episodes, run_experiment

    _load_env()
    tasks = _select_tasks(args)
    if not tasks:
        print(f"no tasks found in {args.tasks_dir}; run `make bench` first")
        return 2
    budget = Budget(max_steps=args.max_steps, max_cost_usd=args.max_cost, max_wall_s=args.max_wall_s,
                    soft_prompt_tokens=args.soft_prompt_tokens)
    paid = _is_paid(args.model)
    kwargs = dict(spec=args.model, toolset=args.toolset, trials=args.trials, budget=budget,
                  concurrency=args.concurrency, effort=args.effort)
    if paid and args.pilot:
        run_experiment(args.run_id, tasks[:PILOT_TASKS], **{**kwargs, "trials": 1})
        eps = [e for e in load_episodes(args.run_id) if e["trial"] == 1][:PILOT_TASKS]
        per_task = statistics.fmean(e["cost_usd"] for e in eps) if eps else 0.0
        total = per_task * len(tasks) * args.trials
        print(f"\nPILOT ({len(eps)} episodes): measured cost per task ${per_task:.4f} "
              f"(max ${max(e['cost_usd'] for e in eps):.4f}).")
        print(f"Extrapolated for {len(tasks)} tasks x {args.trials} trial(s): ${total:.2f} "
              f"(hard cap ${args.max_cost * len(tasks) * args.trials:.2f} at ${args.max_cost}/task).")
        print("Re-run without --pilot and with --yes to approve the full run (finished episodes are reused).")
        return 0
    if paid and not args.yes:
        print(f"{args.model} costs money. Run with --pilot first, then --yes once the cost is approved.")
        return 2
    run_experiment(args.run_id, tasks, **kwargs)
    return cmd_report(argparse.Namespace(run_id=args.run_id, all=False))


def cmd_report(args) -> int:
    from .evals.report import summarize, write_report
    from .evals.viewer.render import render_run

    if args.all:
        runs = sorted(p.parent.name for p in RESULTS_DIR.glob("E*/config.json"))
        for r in runs:
            render_run(r)
        print(f"wrote {write_report(runs)} from runs {runs}")
        return 0
    s = summarize(args.run_id)
    m = s["metrics"]
    print(f"{args.run_id}: resolved {m['resolved']}/{m['episodes']} = {m['resolve_rate']:.1%} "
          f"(95% CI {m['wilson95'][0]:.1%}-{m['wilson95'][1]:.1%}), mean cost ${m['cost_mean']:.4f}, "
          f"stops {m['stop_reasons']}")
    print(f"viewer: {render_run(args.run_id)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="patchloop")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="scripted FakeModel fixes the toy bug")
    d.add_argument("--unsafe-local", action="store_true",
                   help="run on the host in a temp copy of toy_repo/ (development only; never with real repos)")
    d.set_defaults(fn=cmd_demo)

    b = sub.add_parser("bench", help="generate and validate benchmark tasks")
    b.add_argument("--repo", required=True)
    b.add_argument("--target", type=int, default=18)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--strategy", choices=["ast", "llm"], default="ast")
    b.add_argument("--issues", choices=["template", "llm"], default="template")
    b.add_argument("--model", default="claude-haiku-5-5")
    b.add_argument("--max-attempts", type=int, default=400)
    b.add_argument("--yes", action="store_true")
    b.set_defaults(fn=cmd_bench)

    e = sub.add_parser("eval", help="run an experiment")
    e.add_argument("--run-id", required=True)
    e.add_argument("--model", default="claude-haiku-5-5", help="model id, 'openai:<model>', 'fake' or 'oracle'")
    e.add_argument("--toolset", choices=["structured", "bash_only"], default="structured")
    e.add_argument("--effort", choices=["none", "low", "medium", "high"], default="low",
                   help="Claude: output_config.effort; Ollama: reasoning_effort ('none' = thinking off)")
    e.add_argument("--trials", type=int, default=1)
    e.add_argument("--concurrency", type=int, default=4)
    e.add_argument("--max-steps", type=int, default=40)
    e.add_argument("--max-cost", type=float, default=0.15)
    e.add_argument("--max-wall-s", type=float, default=600)
    e.add_argument("--soft-prompt-tokens", type=int, default=80_000,
                   help="compaction threshold; keep below the model's context window (12000 for a 16K local model)")
    e.add_argument("--tasks-dir", default=str(TASKS_DIR))
    e.add_argument("--task", action="append", help="restrict to these instance ids")
    e.add_argument("--include-toy", action="store_true")
    e.add_argument("--limit", type=int)
    e.add_argument("--pilot", action="store_true", help=f"run {PILOT_TASKS} tasks, print measured + extrapolated cost")
    e.add_argument("--yes", action="store_true", help="approve spending for a paid model")
    e.set_defaults(fn=cmd_eval)

    r = sub.add_parser("report", help="summary + viewer for a run, or docs/EVAL_REPORT.md for all E* runs")
    r.add_argument("--run-id")
    r.add_argument("--all", action="store_true")
    r.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    if args.cmd == "report" and not (args.all or args.run_id):
        p.error("report needs --run-id or --all")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
