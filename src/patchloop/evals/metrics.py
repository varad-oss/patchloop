"""Metrics: Wilson intervals, unbiased pass@k / pass^k, aggregates and failure classification."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from math import comb


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k (Chen et al. 2021): P(at least one of k samples, drawn from n, is correct)."""
    if k > n:
        raise ValueError("k must be <= n")
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Unbiased pass^k (tau-bench): P(all k samples, drawn from n without replacement, are correct)."""
    if k > n:
        raise ValueError("k must be <= n")
    return comb(c, k) / comb(n, k)


def classify_failure(ep: dict, task: dict, traj: list[dict]) -> str:
    """One label per unresolved episode, checked in priority order."""
    g = ep.get("grade", {})
    if ep["stop_reason"] == "error" or str(g.get("reason", "")).startswith("infrastructure"):
        return "infrastructure_error"
    if g.get("tampered") or ep.get("tampered"):
        return "tamper_attempt"
    tests_dir = task["tests_dir"]
    for rec in traj:
        if rec.get("event", "step") != "step":  # the "end" record stores tool_calls as a count
            continue
        for call in rec.get("tool_calls", []):
            args = str(call.get("args", ""))
            if call.get("name") == "str_replace" and str(call["args"].get("path", "")).startswith(tests_dir):
                return "tamper_attempt"
            if call.get("name") == "bash" and tests_dir in args and any(
                    w in args for w in ("sed -i", "> ", "rm ", "tee ", "write_text", "open(")):
                return "tamper_attempt"
    if ep["stop_reason"] in ("step_limit", "cost_limit", "time_limit", "loop_detected"):
        return "budget_exhausted"
    calls = ep.get("tool_calls", 0)
    if calls and ep.get("tool_errors", 0) / calls >= 0.4:
        return "tool_misuse"
    bug_file = task["difficulty"]["file"]
    if bug_file not in g.get("touched", []):
        return "never_found_the_bug"
    if g.get("reason") == "broke_pass_to_pass":
        return "broke_other_tests"
    return "wrong_fix"


def _median(xs):
    return statistics.median(xs) if xs else 0


def aggregate(episodes: list[dict], tasks: dict[str, dict]) -> dict:
    n = len(episodes)
    resolved = sum(1 for e in episodes if e["grade"]["resolved"])
    lo, hi = wilson(resolved, n)
    usage = lambda key: [e["usage"][key] for e in episodes]  # noqa: E731
    by_diff: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for e in episodes:
        d = tasks[e["instance_id"]]["difficulty"]
        buckets = {
            "repo": tasks[e["instance_id"]]["repo"],
            "strategy": d["strategy"],
            "mutation": d["mutation"],
            "n_fail": "1" if d["n_fail"] == 1 else ("2-5" if d["n_fail"] <= 5 else "6+"),
            "func_named_in_test": str(d["func_named_in_test"]),
        }
        for dim, val in buckets.items():
            by_diff[dim][val].append(int(e["grade"]["resolved"]))
    out = {
        "episodes": n,
        "tasks": len({e["instance_id"] for e in episodes}),
        "resolved": resolved,
        "resolve_rate": resolved / n if n else 0.0,
        "wilson95": [lo, hi],
        "steps_mean": statistics.fmean([e["steps"] for e in episodes]) if n else 0,
        "steps_median": _median([e["steps"] for e in episodes]),
        "cost_mean": statistics.fmean([e["cost_usd"] for e in episodes]) if n else 0,
        "cost_median": _median([e["cost_usd"] for e in episodes]),
        "cost_total": sum(e["cost_usd"] for e in episodes),
        "wall_mean_s": statistics.fmean([e["wall_s"] for e in episodes]) if n else 0,
        "wall_median_s": _median([e["wall_s"] for e in episodes]),
        "tokens_mean": {k: (statistics.fmean(usage(k)) if n else 0) for k in
                        ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "cache_write_tokens")},
        "compactions_total": sum(e.get("compactions", 0) for e in episodes),
        "episodes_with_compaction": sum(1 for e in episodes if e.get("compactions", 0)),
        "stop_reasons": dict(Counter(e["stop_reason"] for e in episodes)),
        "failure_classes": dict(Counter(e["failure_class"] for e in episodes if not e["grade"]["resolved"])),
        "by_difficulty": {dim: {v: {"n": len(xs), "resolved": sum(xs)} for v, xs in sorted(vals.items())}
                          for dim, vals in by_diff.items()},
    }
    trials: dict[str, list[int]] = defaultdict(list)
    for e in episodes:
        trials[e["instance_id"]].append(int(e["grade"]["resolved"]))
    k_max = min(len(v) for v in trials.values()) if trials else 0
    if k_max > 1:
        out["pass_at_k"] = {k: statistics.fmean(pass_at_k(len(v), sum(v), k) for v in trials.values())
                            for k in range(1, k_max + 1)}
        out["pass_hat_k"] = {k: statistics.fmean(pass_hat_k(len(v), sum(v), k) for v in trials.values())
                             for k in range(1, k_max + 1)}
    return out
