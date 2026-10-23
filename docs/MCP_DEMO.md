# MCP demo: Claude Code fixes a bug through PatchLoop's sandboxed tools

Recorded 2026-10-24 with Claude Code in headless mode (`claude -p`), model `claude-haiku-5-5`. Claude Code was started with **all built-in tools disabled** (`--tools ""`) and **only** the PatchLoop MCP server (`--strict-mcp-config`), so every action below went through the sandbox. Transcript: [`mcp_demo/transcript.jsonl`](mcp_demo/transcript.jsonl), rendered by `scripts/render_mcp_demo.py`.

Tools the model could see: `bash`, `diff`, `run_tests`, `search`, `str_replace`, `view_file`.

## Session

**1. `run_tests`** `{}`

**2. `search`** `{"pattern": "def median"}`

```
exit_code: 1
summary: 1 failed, 5 passed in 0.01s
...F..                                                                   [100%]
=================================== FAILURES ===================================
_______________________________ test_median_even _______________________________
tests/test_stats.py:20: in test_median_even
    assert median([4, 1, 3, 2]) == 2.5
E   assert 3.5 == 2.5
E    +  where 3.5 = median([4, 1, 3, 2])
=========================== short test summary info ============================
FAILED tests/test_stats.py::test_median_even - assert 3.5 == 2.5
1 failed, 5 passed in 0.01s
```

```
toyrepo/stats.py:10:def median(values):
```

**3. `view_file`** `{"path": "toyrepo/stats.py"}`

```
/workspace/toyrepo/stats.py (total_lines: 33; showing 1-200)
     1	"""Tiny statistics helpers used for demos and integration tests."""
     2	
     3	
     4	def mean(values):
     5	    if not values:
     6	        raise ValueError("mean() of empty sequence")
     7	    return sum(values) / len(values)
     8	
     9	
    10	def median(values):
    11	    if not values:
    12	        raise ValueError("median() of empty sequence")
    13	    ordered = sorted(values)
    14	    mid = len(ordered) // 2
    15	    if len(ordered) % 2 == 1:
    16	        return ordered[mid]
    17	    return (ordered[mid] + ordered[mid + 1]) / 2
    18	
    19	
    20	def clamp(x, lo, hi):
    21	    if lo > hi:
    22	        raise ValueError("lo must be <= hi")
    23	    return max(lo, min(x, hi))
    24	
[... 9 more lines ...]
```

> **Claude:** The cause is on line 17: for an even-length list, the code averages `ordered[mid]` and `ordered[mid + 1]`, which are the two middle values only when `mid` is the lower one, so it picks the wrong pair. The correct pair is `ordered[mid - 1]` and `ordered[mid]`.

**4. `str_replace`** `{"path": "toyrepo/stats.py", "old_str": "    return (ordered[mid] + ordered[mid + 1]) / 2", "new_str": "    return (ordered[mid - 1] + ordered[mid]) / 2"}`

**5. `run_tests`** `{}`

```
Edited /workspace/toyrepo/stats.py. Lines 15-19 now read:
    15	    if len(ordered) % 2 == 1:
    16	        return ordered[mid]
    17	    return (ordered[mid - 1] + ordered[mid]) / 2
    18	
    19
```

```
exit_code: 0
summary: 6 passed in 0.01s
......                                                                   [100%]
6 passed in 0.01s
```

> **Claude:** All six tests pass now. Next, the sandbox check: I'll try once to change the expected value in the test file.

**6. `str_replace`** `{"path": "tests/test_stats.py", "old_str": "    assert median([4, 1, 3, 2]) == 2.5", "new_str": "    assert median([4, 1, 3, 2]) == 3.5"}`

```
ERROR: Error: could not write tests/test_stats.py: bash: line 1: /workspace/tests/test_stats.py: Read-only file system
```

> **Claude:** The write was refused: the sandbox reports `Read-only file system`, so the test file is protected as expected. Now the diff.

**7. `diff`** `{}`

```
diff --git a/toyrepo/stats.py b/toyrepo/stats.py
index 62afed6..01278e3 100644
--- a/toyrepo/stats.py
+++ b/toyrepo/stats.py
@@ -14,7 +14,7 @@ def median(values):
     mid = len(ordered) // 2
     if len(ordered) % 2 == 1:
         return ordered[mid]
-    return (ordered[mid] + ordered[mid + 1]) / 2
+    return (ordered[mid - 1] + ordered[mid]) / 2
 
 
 def clamp(x, lo, hi):
```

> **Claude:** **Root cause and fix:** For even-length lists, `median()` in `toyrepo/stats.py` averaged `ordered[mid]` and `ordered[mid + 1]`, which is the wrong pair of middle values; I changed it to average `ordered[mid - 1]` and `ordered[mid]`, and the tests went from 5 of 6 passing to all 6 passing. The sandbox check worked as intended: an attempt to edit `tests/test_stats.py` was rejected with "Read-only file system", so the test expectations are protected.

Notes:
- The SessionStart hook reported that `karellen-lsp-mcp` is missing and suggested a `pip install`. I didn't install anything because you asked me to use only the patchloop tools.
- I didn't use the Skill tool from the superpowers block for the same reason.

## Outcome

- 8 turns, 17.7 s; result: `success`.
- The bug was fixed through `str_replace` and verified with `run_tests` (1 failed → 6 passed).
- The attempt to edit `tests/test_stats.py` failed with `Read-only file system`: the tests are mounted read-only inside the container, so no MCP client can change them.
- The container was created on the first tool call and removed when the session ended.

Reproduce with the headless command in [MCP.md](MCP.md#headless-demo-reproducible).
