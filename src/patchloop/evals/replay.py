"""Replay one trajectory as an animated GIF (terminal style), straight from results/.

    patchloop replay --run-id E1 --episode toolz__keyfilter-negate_condition-009 --out docs/demo.gif

Needs Pillow (`pip install -e ".[dev]"`). Frames are rendered from the JSONL trajectory; nothing is staged.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from ..agent.trajectory import read_trajectory
from ..config import RESULTS_DIR

W, H, PAD, LINE = 960, 540, 22, 19
BG, FG, DIM, ACCENT, OK, BAD, CODE_BG = ("#0f1115", "#e6e6e6", "#8a8f98", "#7aa2f7", "#9ece6a", "#f7768e", "#1a1d24")
FONT_PATHS = ["/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
COLS = 92


def _font(size: int):
    from PIL import ImageFont

    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap(text: str, width: int = COLS, max_lines: int = 99) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines() or [""]:
        out.extend(textwrap.wrap(raw, width, replace_whitespace=False, drop_whitespace=False) or [""])
    return out[:max_lines]


def _frame(header: str, blocks: list[tuple[str, str, int]], footer: str = ""):
    """blocks: (text, colour, max_lines). Returns a PIL image."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f, fb = _font(14), _font(15)
    d.rectangle([0, 0, W, 34], fill=CODE_BG)
    d.text((PAD, 9), header, font=fb, fill=ACCENT)
    y = 46
    for text, colour, max_lines in blocks:
        for line in _wrap(text, max_lines=max_lines):
            if y > H - 40:
                break
            d.text((PAD, y), line, font=f, fill=colour)
            y += LINE
        y += 8
    if footer:
        d.text((PAD, H - 28), footer, font=f, fill=DIM)
    return img


def _args(call: dict) -> str:
    a = call["args"]
    if call["name"] == "str_replace":
        return f"path={a.get('path')}\n- {a.get('old_str', '')}\n+ {a.get('new_str', '')}"
    return json.dumps(a)[:300]


def render_gif(run_id: str, episode: str, out: Path, step_ms: int = 1600) -> Path:
    run_dir = RESULTS_DIR / run_id
    record = json.loads((run_dir / "episodes" / f"{episode}__t1.json").read_text())
    traj = read_trajectory(run_dir / "trajectories" / f"{episode}__t1.jsonl")
    steps = [r for r in traj if r.get("event") == "step"]
    start = next(r for r in traj if r.get("event") == "start")
    title = f"PatchLoop · {episode} · {start['model'].removeprefix('ollama:')} · {start['toolset']} tools"
    issue = start["task"].split("</issue>")[0].replace("<issue>", "").strip()
    frames, durations = [], []

    frames.append(_frame(title, [("ISSUE (the only thing the agent is told)", ACCENT, 1), (issue, FG, 20)],
                         "Docker sandbox: no network · read-only tests · non-root · 1 CPU / 1 GB"))
    durations.append(3500)
    for s in steps:
        blocks: list[tuple[str, str, int]] = []
        if s.get("text"):
            blocks.append((f"model: {s['text'].strip()}", FG, 4))
        observations = [o for o in s.get("observations", []) if "tool" in o]
        for call, obs in zip(s.get("tool_calls", []), observations, strict=False):
            blocks.append((f"→ {call['name']}", ACCENT, 1))
            blocks.append((_args(call), DIM, 6))
            blocks.append((obs["content"].strip(), BAD if obs.get("is_error") else FG, 12))
        if not s.get("tool_calls"):
            blocks.append(("(no tool call: the loop nudges the model to keep going)", DIM, 1))
        footer = (f"step {s['step']}/{record['steps']} · {s['latency_s']:.1f}s · "
                  f"prompt {s['usage']['input_tokens'] + s['usage']['cache_read_tokens']} tokens · $0 (local)")
        frames.append(_frame(title, blocks, footer))
        durations.append(step_ms)
    g = record["grade"]
    verdict = ("GRADER (fresh container, hidden tests): RESOLVED" if g["resolved"]
               else f"GRADER: unresolved ({g['reason']})")
    frames.append(_frame(title, [(verdict, OK if g["resolved"] else BAD, 1),
                                 (f"stop reason: {record['stop_reason']} · {record['steps']} steps · "
                                  f"{record['wall_s']:.0f}s wall time", DIM, 1),
                                 (record.get("patch") or "(empty patch)", FG, 20)],
                         "every frame is rendered from results/"))
    durations.append(5000)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    return out
