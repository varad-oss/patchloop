"""The agent-computer interface: six tools, all executed inside the sandbox Env.

Host-side code here only builds command strings and manipulates text; every command runs
through `env.exec`, which for DockerEnv is a `docker exec` into the episode container.
Tool failures never raise into the loop - they come back as observations with is_error=True.
"""

from __future__ import annotations

import difflib
import posixpath
import re
import shlex
from dataclasses import dataclass

from ..sandbox.base import WORKSPACE, Env
from .models import ToolCall, ToolSpec

HEAD_LINES, TAIL_LINES, MAX_LINE_CHARS = 100, 50, 2000
MAX_OBS_CHARS = 20_000  # ~6K tokens: one observation must never blow a small local context window
VIEW_MAX_LINES, SEARCH_MAX_MATCHES = 200, 50


def truncate(text: str, head: int = HEAD_LINES, tail: int = TAIL_LINES) -> str:
    """Keep the first `head` and last `tail` lines, with an explicit marker in between."""
    lines = [ln if len(ln) <= MAX_LINE_CHARS else ln[:MAX_LINE_CHARS] + " [... line truncated ...]"
             for ln in text.splitlines()]
    if len(lines) > head + tail:
        cut = len(lines) - head - tail
        lines = [*lines[:head], f"[... {cut} lines truncated ...]", *lines[-tail:]]
    out = "\n".join(lines)
    if len(out) > MAX_OBS_CHARS:
        half = MAX_OBS_CHARS // 2
        out = f"{out[:half]}\n[... {len(out) - 2 * half} characters truncated ...]\n{out[-half:]}"
    return out


@dataclass
class Observation:
    content: str
    is_error: bool = False
    submitted: bool = False


class PathError(ValueError):
    pass


def resolve_path(path: str) -> str:
    """Resolve `path` against /workspace and reject anything that escapes it."""
    if not isinstance(path, str) or not path or "\x00" in path:
        raise PathError("path must be a non-empty string")
    full = posixpath.normpath(posixpath.join(WORKSPACE, path))
    if full != WORKSPACE and not full.startswith(WORKSPACE + "/"):
        raise PathError(f"path {path!r} resolves outside {WORKSPACE}; only files in the repository are accessible")
    return full


TOOL_SPECS: dict[str, ToolSpec] = {
    "bash": ToolSpec(
        "bash",
        "Run a shell command in the repository root (/workspace) inside an isolated sandbox with no network. "
        "Each call starts a fresh shell: `cd` and environment variables do not persist between calls. "
        "Returns the exit code and combined stdout/stderr; long output keeps the first 100 and last 50 "
        "lines with a '[... N lines truncated ...]' marker, so filter output (grep, head) when you can. "
        "Use it for anything the other tools do not cover, e.g. running a small Python snippet to "
        "reproduce a bug. Commands are killed after timeout_s seconds.",
        {"type": "object", "properties": {
            "command": {"type": "string", "description": "The bash command to run."},
            "timeout_s": {"type": "integer", "description": "Timeout in seconds (default 60, max 300)."}},
         "required": ["command"]},
    ),
    "view_file": ToolSpec(
        "view_file",
        "Show a file with line numbers, at most 200 lines per call. Use start_line/end_line to page "
        "through longer files; the header tells you the total number of lines. Paths are relative to "
        "the repository root. Errors if the file does not exist or the path leaves the repository.",
        {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "description": "1-based, default 1."},
            "end_line": {"type": "integer", "description": "Inclusive; default start_line + 199."}},
         "required": ["path"]},
    ),
    "search": ToolSpec(
        "search",
        "Search file contents with a regular expression (ripgrep syntax) and return up to 50 matches as "
        "path:line:text. Use it to find where a function is defined or used before opening files. "
        "Optionally restrict to a sub-directory (path) or a file glob such as '*.py'.",
        {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "Directory or file to search, default '.'."},
            "glob": {"type": "string", "description": "Optional glob filter, e.g. '*.py'."}},
         "required": ["pattern"]},
    ),
    "str_replace": ToolSpec(
        "str_replace",
        "Edit a file by replacing one exact occurrence of old_str with new_str. old_str must match the file "
        "exactly (including indentation and whitespace) and must occur exactly once; otherwise the tool "
        "returns an error with the number of matches, and you should include more surrounding lines to make "
        "it unique. On success it shows the edited region. Test files are read-only and cannot be edited.",
        {"type": "object", "properties": {
            "path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}},
         "required": ["path", "old_str", "new_str"]},
    ),
    "run_tests": ToolSpec(
        "run_tests",
        "Run the repository's test suite (or a subset) and return a pass/fail summary plus the failure "
        "output, truncated. selector is passed to pytest, e.g. 'tests/test_x.py::test_name' or "
        "'-k median'. Run this to reproduce the bug first and again after every edit.",
        {"type": "object", "properties": {
            "selector": {"type": "string", "description": "Optional pytest node id(s) or '-k expr'."}}},
    ),
    "submit": ToolSpec(
        "submit",
        "Finish the task. The current state of the repository (its git diff) is your answer. Call this only "
        "after the relevant tests pass. Give a one-paragraph summary of the root cause and the fix.",
        {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
    ),
}

TOOLSETS = {
    "structured": ["bash", "view_file", "search", "str_replace", "run_tests", "submit"],
    "bash_only": ["bash", "submit"],
}


class Toolbox:
    def __init__(self, env: Env, test_cmd: str, toolset: str = "structured"):
        if toolset not in TOOLSETS:
            raise ValueError(f"unknown toolset {toolset!r}")
        self.env = env
        self.test_cmd = test_cmd
        self.toolset = toolset
        self.names = TOOLSETS[toolset]

    def specs(self) -> list[ToolSpec]:
        return [TOOL_SPECS[n] for n in self.names]

    def execute(self, call: ToolCall) -> Observation:
        if call.parse_error:
            return Observation(f"Error: could not parse arguments for {call.name}: {call.parse_error}. "
                               "Send arguments as a JSON object matching the tool schema.", True)
        if call.name not in self.names:
            return Observation(f"Error: unknown tool {call.name!r}. Available tools: {', '.join(self.names)}.", True)
        try:
            return getattr(self, f"_{call.name}")(**call.args)
        except TypeError as e:  # missing / unexpected arguments
            return Observation(f"Error: bad arguments for {call.name}: {e}", True)
        except PathError as e:
            return Observation(f"Error: {e}", True)

    # ------------------------------------------------------------------ tools

    def _bash(self, command: str, timeout_s: int = 60) -> Observation:
        timeout_s = max(1, min(int(timeout_s), 300))
        r = self.env.exec(command, timeout_s)
        return Observation(f"exit_code: {r.exit_code}\n{truncate(r.output)}", is_error=r.timed_out)

    def _check_real(self, full: str) -> None:
        """Reject symlinks that point outside the workspace (resolved inside the sandbox)."""
        r = self.env.exec(f"readlink -m -- {shlex.quote(full)}", 10)
        real = r.output.strip()
        if r.exit_code == 0 and real != WORKSPACE and not real.startswith(WORKSPACE + "/"):
            raise PathError(f"{full} resolves outside {WORKSPACE} (symlink)")

    def _view_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> Observation:
        full = resolve_path(path)
        self._check_real(full)
        start = max(1, int(start_line))
        end = int(end_line) if end_line is not None else start + VIEW_MAX_LINES - 1
        end = min(end, start + VIEW_MAX_LINES - 1)
        if end < start:
            return Observation(f"Error: end_line ({end}) is before start_line ({start}).", True)
        q = shlex.quote(full)
        r = self.env.exec(
            f"test -f {q} || {{ echo 'no such file'; exit 2; }}; echo \"total_lines: $(wc -l < {q})\"; "
            f"awk 'NR>={start} && NR<={end} {{printf \"%6d\\t%s\\n\", NR, $0}}' {q}", 30)
        if r.exit_code != 0:
            return Observation(f"Error: cannot view {path}: {r.output.strip()}", True)
        header, _, body = r.output.partition("\n")
        return Observation(f"{full} ({header}; showing {start}-{end})\n{truncate(body, 200, 0)}")

    def _search(self, pattern: str, path: str = ".", glob: str | None = None) -> Observation:
        full = resolve_path(path)
        g_rg = f"-g {shlex.quote(glob)}" if glob else ""
        g_grep = f"--include={shlex.quote(glob)}" if glob else ""
        p, q = shlex.quote(pattern), shlex.quote(full)
        cmd = (f"cd {WORKSPACE} && if command -v rg >/dev/null; then rg -n --no-heading --color never {g_rg} "
               f"-e {p} {q}; else grep -rnE {g_grep} -e {p} {q}; fi | sed 's#^{WORKSPACE}/##' "
               f"| head -n {SEARCH_MAX_MATCHES + 1}")
        r = self.env.exec(cmd, 30)
        lines = [ln[:300] for ln in r.output.splitlines() if ln.strip()]
        if not lines:
            return Observation(f"No matches for {pattern!r} in {path}.")
        more = len(lines) > SEARCH_MAX_MATCHES
        out = "\n".join(lines[:SEARCH_MAX_MATCHES])
        return Observation(out + ("\n[more than 50 matches; narrow the pattern or path]" if more else ""))

    def _str_replace(self, path: str, old_str: str, new_str: str) -> Observation:
        full = resolve_path(path)
        self._check_real(full)
        content, err = self.env.read_file(full)
        if content is None:
            return Observation(f"Error: cannot read {path}: {err}", True)
        if old_str == "":
            return Observation("Error: old_str must not be empty.", True)
        count = content.count(old_str)
        if count != 1:
            hint = "no match - check whitespace and indentation" if count == 0 else \
                "include more surrounding lines so old_str is unique"
            near = closest_region(content, old_str) if count == 0 else ""
            return Observation(f"Error: old_str occurs {count} times in {path} ({hint}). No change made.{near}", True)
        new_content = content.replace(old_str, new_str, 1)
        w = self.env.write_file(full, new_content)
        if w.exit_code != 0:
            return Observation(f"Error: could not write {path}: {w.output.strip() or 'write failed'}", True)
        first = content[: content.index(old_str)].count("\n") + 1
        last = first + new_str.count("\n")
        lines = new_content.splitlines()
        lo, hi = max(1, first - 2), min(len(lines), last + 2)
        snippet = "\n".join(f"{i:6d}\t{lines[i - 1]}" for i in range(lo, hi + 1))
        return Observation(f"Edited {full}. Lines {lo}-{hi} now read:\n{snippet}")

    def _run_tests(self, selector: str | None = None) -> Observation:
        cmd = self.test_cmd
        if selector:
            cmd = f"python -m pytest -p no:cacheprovider {' '.join(shlex.quote(s) for s in shlex.split(selector))}"
        r = self.env.exec(f"{cmd} -q --tb=short 2>&1", 300)
        summary = summarize_pytest(r.output)
        return Observation(f"exit_code: {r.exit_code}\nsummary: {summary}\n{truncate(r.output)}",
                           is_error=r.timed_out)

    def _submit(self, summary: str = "") -> Observation:
        return Observation("Submitted. The episode is over.", submitted=True)


def closest_region(content: str, old_str: str, min_ratio: float = 0.5) -> str:
    """For a failed exact match, show the most similar block of the file so the model can copy it verbatim
    instead of re-typing code from memory."""
    lines, want = content.splitlines(), old_str.strip("\n").splitlines()
    if not lines or not want:
        return ""
    n = len(want)
    target = "\n".join(s.strip() for s in want)
    best, best_i = 0.0, 0
    for i in range(0, max(1, len(lines) - n + 1)):
        window = "\n".join(s.strip() for s in lines[i:i + n])
        sm = difflib.SequenceMatcher(None, target, window, autojunk=False)
        if sm.real_quick_ratio() <= best or sm.quick_ratio() <= best:
            continue
        r = sm.ratio()
        if r > best:
            best, best_i = r, i
    if best < min_ratio:
        return ""
    lo, hi = max(0, best_i - 1), min(len(lines), best_i + n + 1)
    shown = "\n".join(f"{k + 1:6d}\t{lines[k]}" for k in range(lo, hi))
    return (f"\nThe most similar region of the file (lines {lo + 1}-{hi}) is shown below. Copy old_str from it "
            f"exactly, without the line-number prefix:\n{shown}")


_SUMMARY_RE = re.compile(r"=+ (.*(?:passed|failed|error|no tests ran).*?) (?:in [\d.]+s.*)?=+\s*$", re.M)


def summarize_pytest(output: str) -> str:
    matches = _SUMMARY_RE.findall(output)
    if matches:
        return matches[-1].strip()
    tail = [ln for ln in output.strip().splitlines() if ln.strip()]
    return tail[-1][:200] if tail else "no output"
