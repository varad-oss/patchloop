import pytest

from patchloop.agent.models import ToolCall
from patchloop.agent.tools import TOOLSETS, PathError, Toolbox, resolve_path, summarize_pytest, truncate


@pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "a/../../x", "/workspace/../root", "", "a\x00b"])
def test_traversal_rejected(path):
    with pytest.raises(PathError):
        resolve_path(path)


@pytest.mark.parametrize("path,expected", [("pkg/mod.py", "/workspace/pkg/mod.py"), (".", "/workspace"),
                                           ("/workspace/a/./b.py", "/workspace/a/b.py"), ("a/../b", "/workspace/b")])
def test_paths_inside_workspace(path, expected):
    assert resolve_path(path) == expected


def test_truncate_marker():
    text = "\n".join(f"line {i}" for i in range(400))
    out = truncate(text).splitlines()
    assert out[0] == "line 0" and out[99] == "line 99"
    assert out[100] == "[... 250 lines truncated ...]"
    assert out[-1] == "line 399" and len(out) == 151


def test_truncate_short_untouched():
    assert truncate("a\nb") == "a\nb"


def test_truncate_long_line():
    assert "[... line truncated ...]" in truncate("x" * 5000)


def run(env, name, **args):
    return Toolbox(env, "pytest").execute(ToolCall("1", name, args))


def test_str_replace_success_shows_snippet(mem_env):
    obs = run(mem_env, "str_replace", path="pkg/mod.py", old_str="x + 1", new_str="x + 2")
    assert not obs.is_error
    assert "x + 2" in mem_env.files["/workspace/pkg/mod.py"]
    assert "4\t    return x + 2" in obs.content


def test_str_replace_zero_matches(mem_env):
    obs = run(mem_env, "str_replace", path="pkg/mod.py", old_str="nope", new_str="y")
    assert obs.is_error and "occurs 0 times" in obs.content


def test_str_replace_multiple_matches(mem_env):
    obs = run(mem_env, "str_replace", path="pkg/mod.py", old_str="= 1", new_str="= 2")
    assert obs.is_error and "occurs 2 times" in obs.content
    assert "= 1" in mem_env.files["/workspace/pkg/mod.py"]  # unchanged


def test_str_replace_readonly_tests(mem_env):
    obs = run(mem_env, "str_replace", path="tests/test_mod.py", old_str="True", new_str="False")
    assert obs.is_error and "Read-only" in obs.content


def test_str_replace_traversal(mem_env):
    obs = run(mem_env, "str_replace", path="../../etc/hosts", old_str="a", new_str="b")
    assert obs.is_error and "outside /workspace" in obs.content


def test_unknown_tool_and_bad_args(mem_env):
    assert "unknown tool" in run(mem_env, "rm_rf").content
    obs = run(mem_env, "str_replace", path="pkg/mod.py")
    assert obs.is_error and "bad arguments" in obs.content


def test_malformed_json_call_becomes_error(mem_env):
    obs = Toolbox(mem_env, "pytest").execute(ToolCall("1", "bash", {}, parse_error="invalid JSON"))
    assert obs.is_error and "could not parse" in obs.content


def test_bash_only_toolset_hides_structured_tools(mem_env):
    tb = Toolbox(mem_env, "pytest", "bash_only")
    assert [s.name for s in tb.specs()] == TOOLSETS["bash_only"] == ["bash", "submit"]
    assert tb.execute(ToolCall("1", "view_file", {"path": "x"})).is_error


def test_submit(mem_env):
    assert run(mem_env, "submit", summary="done").submitted


def test_run_tests_selector_is_quoted(mem_env):
    run(mem_env, "run_tests", selector="tests/test_mod.py::test_f; rm -rf /")
    # each token is quoted, so ';' stays inside a pytest argument instead of starting a new command
    assert "'tests/test_mod.py::test_f;' rm -rf /" in mem_env.commands[-1]


def test_summarize_pytest():
    assert summarize_pytest("...\n1 failed, 5 passed in 0.12s\n") == "1 failed, 5 passed in 0.12s"
    assert summarize_pytest("x\n===== 2 passed in 0.1s =====\n") == "2 passed"
