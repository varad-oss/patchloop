"""Render a Claude Code stream-json transcript of the MCP demo into docs/MCP_DEMO.md.

Usage: python scripts/render_mcp_demo.py <raw transcript.jsonl>
Keeps only the conversation (tool list, model, calls, results, text, final stats). Session ids, local paths and
account details from the raw init event are dropped, so the committed transcript is safe to publish.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
raw = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]

clean = []
for e in raw:
    t = e.get("type")
    if t == "system" and e.get("subtype") == "init":
        clean.append({"type": "init", "model": e.get("model"), "tools": e.get("tools"),
                      "mcp_servers": [{"name": s["name"], "status": s["status"]} for s in e.get("mcp_servers", [])]})
    elif t in ("assistant", "user"):
        clean.append({"type": t, "content": e["message"]["content"]})
    elif t == "result":
        clean.append({"type": "result", "subtype": e.get("subtype"), "num_turns": e.get("num_turns"),
                      "duration_s": round(e.get("duration_ms", 0) / 1000, 1)})
out_dir = ROOT / "docs" / "mcp_demo"
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "transcript.jsonl").write_text("".join(json.dumps(c) + "\n" for c in clean))


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(x.get("text", "") for x in content)


def unwrap(text: str) -> str:
    try:
        return json.loads(text)["result"]
    except (ValueError, KeyError, TypeError):
        return text


init = next(c for c in clean if c["type"] == "init")
final = next(c for c in clean if c["type"] == "result")
md = ["# MCP demo: Claude Code fixes a bug through PatchLoop's sandboxed tools", "",
      f"Recorded 2026-10-24 with Claude Code in headless mode (`claude -p`), model `{init['model']}`. Claude Code was "
      "started with **all built-in tools disabled** (`--tools \"\"`) and **only** the PatchLoop MCP server "
      "(`--strict-mcp-config`), so every action below went through the sandbox. Transcript: "
      "[`mcp_demo/transcript.jsonl`](mcp_demo/transcript.jsonl), rendered by `scripts/render_mcp_demo.py`.", "",
      f"Tools the model could see: {', '.join('`' + t.removeprefix('mcp__patchloop__') + '`' for t in init['tools'])}.", "",
      "## Session", ""]
step = 0
for c in clean:
    if c["type"] == "assistant":
        for b in c["content"]:
            if b["type"] == "text" and b["text"].strip():
                md += [f"> **Claude:** {b['text'].strip()}", ""]
            elif b["type"] == "tool_use":
                step += 1
                md += [f"**{step}. `{b['name'].removeprefix('mcp__patchloop__')}`** `{json.dumps(b['input'])}`", ""]
    elif c["type"] == "user":
        for b in c["content"]:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                body = unwrap(text_of(b["content"])).strip()
                lines = body.splitlines()
                if len(lines) > 25:
                    body = "\n".join(lines[:25] + [f"[... {len(lines) - 25} more lines ...]"])
                md += ["```", body, "```", ""]
md += ["## Outcome", "",
       f"- {final['num_turns']} turns, {final['duration_s']} s; result: `{final['subtype']}`.",
       "- The bug was fixed through `str_replace` and verified with `run_tests` (1 failed → 6 passed).",
       "- The attempt to edit `tests/test_stats.py` failed with `Read-only file system`: the tests are mounted read-only "
       "inside the container, so no MCP client can change them.",
       "- The container was created on the first tool call and removed when the session ended.", "",
       "Reproduce with the headless command in [MCP.md](MCP.md#headless-demo-reproducible)."]
(ROOT / "docs" / "MCP_DEMO.md").write_text("\n".join(md) + "\n")
print("wrote docs/MCP_DEMO.md and docs/mcp_demo/transcript.jsonl")
