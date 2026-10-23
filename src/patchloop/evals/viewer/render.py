"""One static, self-contained HTML page per run: every episode, every step, and the final diff."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from ...agent.trajectory import read_trajectory
from ...config import RESULTS_DIR

CSS = """
:root{--bg:#fafafa;--fg:#1d1d1f;--muted:#666;--card:#fff;--line:#e3e3e3;--ok:#1a7f37;--bad:#cf222e;--code:#f4f4f4}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#e8e8e8;--muted:#999;--card:#1e1e1e;--line:#333;--ok:#3fb950;--bad:#f85149;--code:#262626}}
body{font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;max-width:1100px;padding:16px}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:8px 0;padding:8px 12px}
summary{cursor:pointer;font-weight:600} .ok{color:var(--ok)} .bad{color:var(--bad)} .muted{color:var(--muted)}
pre{background:var(--code);padding:8px;border-radius:6px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;max-height:420px}
.step{border-top:1px solid var(--line);padding:6px 0} .tool{font-family:ui-monospace,monospace;font-weight:600}
table{border-collapse:collapse} td,th{padding:2px 10px;border-bottom:1px solid var(--line);text-align:left}
"""


def _step_html(rec: dict) -> str:
    parts = [f'<div class="step"><b>step {rec["step"]}</b> <span class="muted">${rec.get("cost_usd", 0):.4f} · '
             f'{rec.get("latency_s", 0)}s · in {rec["usage"]["input_tokens"]} / out {rec["usage"]["output_tokens"]} tokens</span>']
    if rec.get("text"):
        parts.append(f"<p>{escape(rec['text'])}</p>")
    for call, obs in zip(rec.get("tool_calls", []), [o for o in rec.get("observations", []) if "tool" in o], strict=False):
        cls = "bad" if obs.get("is_error") else ""
        parts.append(f'<div class="tool {cls}">{escape(call["name"])}</div>'
                     f'<pre>{escape(json.dumps(call["args"], indent=1)[:4000])}</pre><pre>{escape(obs["content"][:6000])}</pre>')
    for o in rec.get("observations", []):
        if "nudge" in o:
            parts.append(f'<p class="muted">nudge: {escape(o["nudge"])}</p>')
    parts.append("</div>")
    return "".join(parts)


def render_run(run_id: str) -> Path:
    run_dir = RESULTS_DIR / run_id
    episodes = [json.loads(p.read_text()) for p in sorted((run_dir / "episodes").glob("*.json"))]
    rows, blocks = [], []
    for e in episodes:
        key = f"{e['instance_id']}__t{e['trial']}"
        ok = e["grade"]["resolved"]
        rows.append(f'<tr><td><a href="#{key}">{escape(key)}</a></td><td class="{"ok" if ok else "bad"}">'
                    f'{"resolved" if ok else escape(str(e.get("failure_class")))}</td><td>{e["stop_reason"]}</td>'
                    f'<td>{e["steps"]}</td><td>${e["cost_usd"]:.4f}</td></tr>')
        tpath = run_dir / "trajectories" / f"{key}.jsonl"
        traj = read_trajectory(tpath) if tpath.exists() else []
        steps = "".join(_step_html(r) for r in traj if r.get("event") == "step")
        comp = "".join(f'<p class="muted">compaction at step {r["step"]}</p><pre>{escape(r["summary"][:3000])}</pre>'
                       for r in traj if r.get("event") == "compaction")
        blocks.append(f'<details id="{key}"><summary>{escape(key)} — '
                      f'<span class="{"ok" if ok else "bad"}">{"resolved" if ok else "unresolved"}</span> '
                      f'<span class="muted">({e["stop_reason"]}, grade: {escape(str(e["grade"].get("reason")))})</span>'
                      f'</summary>{comp}{steps}<h4>Final diff</h4><pre>{escape(e.get("patch") or "(empty)")}</pre></details>')
    html = (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><title>PatchLoop {escape(run_id)}</title><style>{CSS}</style></head><body>"
            f"<h1>PatchLoop run {escape(run_id)}</h1><table><tr><th>episode</th><th>result</th><th>stop</th>"
            f"<th>steps</th><th>cost</th></tr>{''.join(rows)}</table>{''.join(blocks)}</body></html>")
    out = run_dir / "viewer.html"
    out.write_text(html)
    return out
