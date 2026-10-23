"""Live terminal dashboard for running experiments. Read-only: it only reads results/ every few seconds.

    patchloop progress --runs effort-low-r2:5 E1:36 E2:36
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import RESULTS_DIR

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
# Seconds per episode before any episode of a run has finished (measured on the 5-task effort check).
PRIOR_EPISODE_S = 600.0


def _bar(done: float, total: int, width: int) -> str:
    frac = 0 if total == 0 else min(1.0, done / total)
    full = int(frac * width)
    part = " ▏▎▍▌▋▊▉"[int((frac * width - full) * 8)] if full < width else ""
    return "█" * full + part + " " * (width - full - len(part))


def _fmt(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None  # file is being written


def _live_episode(run_dir: Path) -> dict | None:
    """The trajectory that has no episode record yet = the episode in progress."""
    done = {p.stem for p in (run_dir / "episodes").glob("*.json")}
    live = [p for p in (run_dir / "trajectories").glob("*.jsonl") if p.stem not in done]
    if not live:
        return None
    path = max(live, key=lambda p: p.stat().st_mtime)
    steps, start, last_tool = 0, None, ""
    try:
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("event") == "start":
                start = rec["ts"]
            elif rec.get("event") == "step":
                steps = rec["step"]
                calls = rec.get("tool_calls") or []
                last_tool = calls[0]["name"] if calls else "(no tool)"
    except (OSError, json.JSONDecodeError):
        pass
    return {"id": path.stem, "steps": steps, "elapsed": time.time() - start if start else 0, "tool": last_tool}


def snapshot(runs: list[tuple[str, int]]) -> dict:
    rows, remaining_s, total_done, total_all = [], 0.0, 0, 0
    for name, total in runs:
        run_dir = RESULTS_DIR / name
        eps = [e for e in (_read_json(p) for p in (run_dir / "episodes").glob("*.json")) if e]
        resolved = sum(1 for e in eps if e["grade"]["resolved"])
        walls = [e.get("episode_wall_s") or e.get("wall_s") or 0 for e in eps]
        avg = sum(walls) / len(walls) if walls else PRIOR_EPISODE_S
        live = _live_episode(run_dir) if run_dir.exists() and len(eps) < total else None
        left = max(0, total - len(eps))
        remaining_s += left * avg - (min(live["elapsed"], avg) if live else 0)
        rows.append({"name": name, "done": len(eps), "total": total, "resolved": resolved, "avg": avg,
                     "live": live, "estimated": not walls})
        total_done += len(eps)
        total_all += total
    return {"rows": rows, "remaining_s": max(0.0, remaining_s), "done": total_done, "total": total_all}


def render(snap: dict, started: float) -> str:
    width = max(20, min(50, shutil.get_terminal_size((90, 20)).columns - 45))
    out = [f"{BOLD}PatchLoop experiments{RESET}  {DIM}{datetime.now():%H:%M:%S} · refreshes every 5 s · "
           f"Ctrl+C to close (runs keep going){RESET}", ""]
    for r in snap["rows"]:
        live_frac = 0.0
        if r["live"]:
            live_frac = min(0.95, r["live"]["elapsed"] / r["avg"])
        rate = f"{r['resolved']}/{r['done']} resolved" if r["done"] else "-"
        colour = GREEN if r["done"] and r["resolved"] else (RED if r["done"] else DIM)
        status = "done" if r["done"] >= r["total"] else ("running" if r["live"] else "waiting")
        out.append(f"{r['name']:<14} {_bar(r['done'] + live_frac, r['total'], width)} "
                   f"{r['done']:>2}/{r['total']:<2} {colour}{rate:<16}{RESET} {DIM}{status}{RESET}")
        if r["live"]:
            lv = r["live"]
            out.append(f"{DIM}  └ {lv['id'][:52]:<52} step {lv['steps']:>2}/40 · {_fmt(lv['elapsed'])} · "
                       f"last: {lv['tool']}{RESET}")
    eta = snap["remaining_s"]
    finish = datetime.now() + timedelta(seconds=eta)
    est = any(r["estimated"] for r in snap["rows"] if r["done"] < r["total"])
    out += ["", f"{BOLD}Overall{RESET}        {_bar(snap['done'], snap['total'], width)} {snap['done']}/{snap['total']} episodes",
            f"Time left     ~{_fmt(eta)}  (finishes around {finish:%H:%M})"
            + (f"  {DIM}* partly estimated: runs with no finished episode use {_fmt(PRIOR_EPISODE_S)}/episode{RESET}" if est else ""),
            f"{DIM}Watching for {_fmt(time.time() - started)}. Every number comes from results/.{RESET}"]
    return "\n".join(out)


def watch(runs: list[tuple[str, int]], interval: float = 5.0, once: bool = False) -> None:
    started = time.time()
    try:
        while True:
            frame = render(snapshot(runs), started)
            if once:
                print(frame)
                return
            sys.stdout.write("\033[H\033[J" + frame + "\n")
            sys.stdout.flush()
            snap = snapshot(runs)
            if snap["done"] >= snap["total"]:
                sys.stdout.write("\033[H\033[J" + render(snap, started) + f"\n\n{GREEN}All runs finished.{RESET}\n")
                return
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nClosed the dashboard. The experiments are still running.")


def parse_runs(specs: list[str]) -> list[tuple[str, int]]:
    out = []
    for s in specs:
        name, _, n = s.partition(":")
        out.append((name, int(n) if n else len(json.loads((RESULTS_DIR / name / "config.json").read_text())["tasks"])))
    return out
