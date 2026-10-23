"""Write docs/project/BUG_REPORT_REVIEW.md: 10 seeded bug reports for the manual review the spec asks for."""

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "project" / "BUG_REPORT_REVIEW.md"
if OUT.exists() and "## Review result" in OUT.read_text() and "--force" not in sys.argv:
    sys.exit(f"{OUT} already holds a completed review; pass --force to overwrite it")
tasks = sorted((json.loads(p.read_text()) for p in (ROOT / "bench" / "tasks").glob("*.json")),
               key=lambda t: t["instance_id"])
sample = random.Random(2026).sample(tasks, 10)

out = ["# Bug-report review (manual, 10 tasks)", "",
       "The spec asks a human to review ten generated bug reports. These ten were drawn with a fixed seed "
       "(`scripts/make_review_sheet.py`, seed 2026). For each one, read the report **first**, answer the three "
       "questions, then open the hidden bug to check your answers. Tick a box by changing `[ ]` to `[x]`.", "",
       "Questions:", "1. **Reproducible:** could a developer reproduce the problem from this text alone?",
       "2. **No leak:** does it avoid giving away the file, line or code to change?",
       "3. **Realistic:** does it read like something a user might plausibly file?", "",
       "If a report fails, note why in the comment line. If more than 2 of 10 fail question 1 or 2, tell Claude "
       "to tighten `benchgen/issues.py` and regenerate.", ""]
for i, t in enumerate(sample, 1):
    d = t["difficulty"]
    out += [f"## {i}. `{t['instance_id']}`", "",
            f"_{d['mutation']}, {d['n_fail']} failing test(s), function named in a test: {d['func_named_in_test']}_",
            "", "**Report as the agent sees it:**", "", "> " + t["problem_statement"].replace("\n", "\n> "), "",
            "- [ ] Reproducible   - [ ] No leak   - [ ] Realistic", "- Comment: ", "",
            "<details><summary>Show the injected bug (after answering)</summary>", "", "```diff",
            t["bug_patch"].rstrip(), "```", "", "</details>", ""]
OUT.write_text("\n".join(out))
print("wrote docs/project/BUG_REPORT_REVIEW.md")
