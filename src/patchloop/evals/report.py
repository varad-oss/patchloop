"""Reports generated ONLY from results/. Every number in docs/EVAL_REPORT.md comes from here."""

from __future__ import annotations

import json
from html import escape
from math import comb
from pathlib import Path

from ..agent.trajectory import read_trajectory
from ..config import RESULTS_DIR, ROOT, load_tasks
from .metrics import aggregate
from .runner import load_episodes


def _tasks_by_id() -> dict[str, dict]:
    tasks = {t["instance_id"]: t for t in load_tasks()}
    for extra in ("toy", "tasks_llm"):
        tasks.update({t["instance_id"]: t for t in load_tasks(ROOT / "bench" / extra)})
    return tasks


def summarize(run_id: str) -> dict:
    run_dir = RESULTS_DIR / run_id
    episodes = load_episodes(run_id)
    if not episodes:
        raise SystemExit(f"no episodes in {run_dir}")
    cfg = json.loads((run_dir / "config.json").read_text())
    summary = {"run_id": run_id, "config": cfg, "metrics": aggregate(episodes, _tasks_by_id())}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


CHART_THEMES = {  # GitHub's own light and dark palettes, so the chart blends into either README theme
    "light": {"bg": "#ffffff", "grid": "#d0d7de", "text": "#1f2328", "muted": "#656d76", "bar": "#0969da",
              "whisker": "#1f2328"},
    "dark": {"bg": "#0d1117", "grid": "#30363d", "text": "#e6edf3", "muted": "#8b949e", "bar": "#2f81f7",
             "whisker": "#f0f6fc"},
}


def svg_resolve_chart(summaries: list[dict], theme: str = "light") -> str:
    """Horizontal bars: resolve rate, with the 95% Wilson interval as a whisker and the value as a label."""
    c = CHART_THEMES[theme]
    w, row, left, right = 640, 44, 190, 70
    h = 40 + row * len(summaries)
    scale = w - left - right
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
             f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" font-size="13">',
             f'<rect width="{w}" height="{h}" rx="8" fill="{c["bg"]}"/>']
    for x in (0, 0.25, 0.5, 0.75, 1.0):
        px = left + x * scale
        parts.append(f'<line x1="{px:.1f}" y1="26" x2="{px:.1f}" y2="{h - 10}" stroke="{c["grid"]}"/>'
                     f'<text x="{px:.1f}" y="18" text-anchor="middle" fill="{c["muted"]}" font-size="11">{int(x * 100)}%</text>')
    for i, s in enumerate(summaries):
        m, y = s["metrics"], 34 + i * row
        lo, hi = m["wilson95"]
        label = f'{s["run_id"]} · {s["config"]["toolset"].replace("_", " ")}'
        bar_w = max(2.0, m["resolve_rate"] * scale)
        parts.append(
            f'<text x="{left - 12}" y="{y + 17}" text-anchor="end" fill="{c["text"]}" font-weight="600">{escape(label)}</text>'
            f'<rect x="{left}" y="{y + 4}" width="{bar_w:.1f}" height="18" rx="3" fill="{c["bar"]}"/>'
            f'<line x1="{left + lo * scale:.1f}" y1="{y + 13}" x2="{left + hi * scale:.1f}" y2="{y + 13}" '
            f'stroke="{c["whisker"]}" stroke-width="2"/>'
            f'<line x1="{left + lo * scale:.1f}" y1="{y + 8}" x2="{left + lo * scale:.1f}" y2="{y + 18}" stroke="{c["whisker"]}" stroke-width="2"/>'
            f'<line x1="{left + hi * scale:.1f}" y1="{y + 8}" x2="{left + hi * scale:.1f}" y2="{y + 18}" stroke="{c["whisker"]}" stroke-width="2"/>'
            f'<text x="{left + hi * scale + 8:.1f}" y="{y + 17}" fill="{c["text"]}" font-weight="600">'
            f'{m["resolve_rate"]:.1%}</text>')
    parts.append("</svg>")
    return "".join(parts)


def run_section(s: dict) -> str:
    m, c = s["metrics"], s["config"]
    lo, hi = m["wilson95"]
    t = m["tokens_mean"]
    lines = [
        f"### {s['run_id']}",
        "",
        f"Model `{c['model']}` (effort `{c.get('effort')}`), toolset `{c['toolset']}`, {m['tasks']} tasks x "
        f"{c['trials']} trial(s) = {m['episodes']} episodes. Pricing table checked {c.get('pricing_checked')}.",
        "",
        "| metric | value |", "|---|---|",
        f"| resolved | {m['resolved']}/{m['episodes']} = **{m['resolve_rate']:.1%}** (95% Wilson {lo:.1%}-{hi:.1%}) |",
        f"| steps mean / median | {m['steps_mean']:.1f} / {m['steps_median']} |",
        f"| cost per task mean / median | ${m['cost_mean']:.4f} / ${m['cost_median']:.4f} (total ${m['cost_total']:.4f}) |",
        f"| wall time mean / median | {m['wall_mean_s']:.1f}s / {m['wall_median_s']:.1f}s |",
        f"| tokens mean (input / output / thinking) | {t['input_tokens']:.0f} / {t['output_tokens']:.0f} / {t['thinking_tokens']:.0f} |",
        f"| cache read / write tokens mean | {t['cache_read_tokens']:.0f} / {t['cache_write_tokens']:.0f} |",
        f"| compactions | {m['compactions_total']} (in {m['episodes_with_compaction']} episodes) |",
        "",
        "Stop reasons: " + ", ".join(f"`{k}` {v}" for k, v in sorted(m["stop_reasons"].items())),
        "",
        "Failure classes (unresolved): " + (", ".join(f"`{k}` {v}" for k, v in sorted(m["failure_classes"].items())) or "none"),
        "",
    ]
    if "pass_at_k" in m:
        lines += ["| k | pass@k | pass^k |", "|---|---|---|"]
        lines += [f"| {k} | {m['pass_at_k'][k]:.3f} | {m['pass_hat_k'][k]:.3f} |" for k in m["pass_at_k"]]
        lines.append("")
    lines += ["<details><summary>Breakdown by difficulty</summary>", ""]
    for dim, vals in m["by_difficulty"].items():
        lines += [f"**{dim}**: " + ", ".join(f"{v}: {d['resolved']}/{d['n']}" for v, d in vals.items()), ""]
    lines += ["</details>", "", f"Trajectory viewer: `results/{s['run_id']}/viewer.html`", ""]
    return "\n".join(lines)


def failure_examples(run_id: str, n: int = 3) -> str:
    eps = [e for e in load_episodes(run_id) if not e["grade"]["resolved"]]
    seen, out = set(), []
    for e in eps:
        if e["failure_class"] in seen:
            continue
        seen.add(e["failure_class"])
        traj = read_trajectory(RESULTS_DIR / run_id / "trajectories" / f"{e['instance_id']}__t{e['trial']}.jsonl")
        last_texts = [r.get("text", "") for r in traj if r.get("event") == "step" and r.get("text")][-2:]
        out.append(f"- **{e['failure_class']}** - `{e['instance_id']}` (stop `{e['stop_reason']}`, grade "
                   f"`{e['grade'].get('reason')}`, {e['steps']} steps). Last model text: "
                   f"\"{' / '.join(t[:200].replace(chr(10), ' ') for t in last_texts) or '(none)'}\"")
        if len(out) == n:
            break
    return "\n".join(out) or "- (no unresolved episodes)"


LIMITATIONS = """## Limitations

- **Contamination.** toolz and boltons are almost certainly in the model's training data. The injected
  bugs are new, but familiarity with the original code can help the model spot what changed.
- **Synthetic bugs.** Strategy-A mutations (flipped comparisons, off-by-one, removed guards, ...) are
  easier to localize than real-world bugs; most are a single-line change.
- **Small n.** With ~30 tasks, the 95% interval on a resolve rate is roughly +/-15 points; differences
  between runs smaller than that are not evidence of anything.
- **Template bug reports.** By default the issue text is generated from the failing test names and
  assertion output, which is more structured than a real user's report.
"""


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar test on the discordant pairs (b: only A solved, c: only B solved)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_section(a: str, b: str) -> str:
    ea = {e["instance_id"]: e["grade"]["resolved"] for e in load_episodes(a) if e["trial"] == 1}
    eb = {e["instance_id"]: e["grade"]["resolved"] for e in load_episodes(b) if e["trial"] == 1}
    common = sorted(set(ea) & set(eb))
    only_a = [t for t in common if ea[t] and not eb[t]]
    only_b = [t for t in common if eb[t] and not ea[t]]
    both = [t for t in common if ea[t] and eb[t]]
    p = mcnemar_exact(len(only_a), len(only_b))
    lines = [f"## Paired comparison: {a} vs {b}", "",
             f"Same {len(common)} tasks, trial 1. Both resolved: {len(both)}. Only {a}: {len(only_a)}. "
             f"Only {b}: {len(only_b)}. Exact McNemar test on the discordant pairs: **p = {p:.3f}**.", "",
             f"- only {a}: " + (", ".join(f"`{t}`" for t in only_a) or "none"),
             f"- only {b}: " + (", ".join(f"`{t}`" for t in only_b) or "none"), ""]
    return "\n".join(lines)


def diagnostics_section(run_ids: list[str]) -> str:
    """Behavioural diagnostics computed from trajectories: localization, editing, idle turns, compaction."""
    tasks = _tasks_by_id()
    rows = ["## Behavioural diagnostics", "",
            "| run | edited the buggy file | unresolved with empty patch | steps without a tool call | "
            "resolved, episodes with compaction | resolved, episodes without |", "|---|---|---|---|---|---|"]
    for r in run_ids:
        eps = load_episodes(r)
        edited = sum(tasks[e["instance_id"]]["difficulty"]["file"] in e["grade"].get("touched", []) for e in eps)
        empty = sum(1 for e in eps if not e["grade"]["resolved"] and e["grade"].get("reason") == "empty_patch")
        unresolved = sum(1 for e in eps if not e["grade"]["resolved"])
        steps = idle = 0
        for e in eps:
            path = RESULTS_DIR / r / "trajectories" / f"{e['instance_id']}__t{e['trial']}.jsonl"
            for rec in read_trajectory(path) if path.exists() else []:
                if rec.get("event") == "step":
                    steps += 1
                    idle += not rec.get("tool_calls")
        comp = [e for e in eps if e.get("compactions")]
        nocomp = [e for e in eps if not e.get("compactions")]
        res = lambda xs: f"{sum(e['grade']['resolved'] for e in xs)}/{len(xs)}"  # noqa: E731
        rows.append(f"| {r} | {edited}/{len(eps)} | {empty}/{unresolved} | {idle}/{steps} "
                    f"({idle / max(1, steps):.0%}) | {res(comp)} | {res(nocomp)} |")
    rows += ["", "Compaction correlates with failure, but long episodes are also the hard ones, so this is not "
             "evidence that compaction causes failure.", ""]
    return "\n".join(rows)


CHART_HTML = ('<picture><source media="(prefers-color-scheme: dark)" srcset="{prefix}results/resolve_rates-dark.svg">'
              '<img src="{prefix}results/resolve_rates.svg" width="640" '
              'alt="Resolve rate with 95% Wilson intervals per run"></picture>')


def write_report(run_ids: list[str], out: Path = ROOT / "docs" / "EVAL_REPORT.md") -> Path:
    summaries = [summarize(r) for r in run_ids]
    for theme in ("light", "dark"):
        suffix = "" if theme == "light" else "-dark"
        (RESULTS_DIR / f"resolve_rates{suffix}.svg").write_text(svg_resolve_chart(summaries, theme))
    body = ["# PatchLoop evaluation report", "",
            "_Generated by `patchloop report --all` from `results/`. Do not edit by hand._", "",
            "## Summary", "", "| run | model | toolset | tasks x trials | resolved | 95% CI | mean cost/task |",
            "|---|---|---|---|---|---|---|"]
    for s in summaries:
        m, c = s["metrics"], s["config"]
        body.append(f"| {s['run_id']} | {c['model']} | {c['toolset']} | {m['tasks']}x{c['trials']} | "
                    f"{m['resolve_rate']:.1%} | {m['wilson95'][0]:.1%}-{m['wilson95'][1]:.1%} | ${m['cost_mean']:.4f} |")
    body += ["", CHART_HTML.format(prefix="../"), "", "## Runs", ""]
    body += [run_section(s) for s in summaries]
    if {"E1", "E2"} <= set(run_ids):
        body.append(paired_section("E1", "E2"))
    body.append(diagnostics_section(run_ids))
    body += ["Annotated failure examples and interpretation: [EVAL_ANALYSIS.md](EVAL_ANALYSIS.md).", ""]
    body += ["## Failure analysis", ""]
    for r in run_ids:
        body += [f"### {r}", "", failure_examples(r), ""]
    body.append(LIMITATIONS)
    out.write_text("\n".join(body))
    return out
