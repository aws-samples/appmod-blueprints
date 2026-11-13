"""Exit-code semantics of `idc:configure` (workshop/Taskfile.yaml).

A standalone `task idc:configure` must exit non-zero when IDC configuration fails
(an operator re-run reported rc=0 on a failure on event 9d588683), while the
`task install` path (post-install) stays tolerant unless IDC_STRICT=true.

The outcome snippet is read verbatim from the Taskfile, its go-task variables filled
in, and run with bash. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_idc_configure_strict.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
TEMPLATE_VAR = re.compile(r'\{\{\s*\.([A-Z0-9_]+)\s*(?:\|\s*default\s+"([^"]*)"\s*)?\}\}')


def _tasks():
    with open(TASKFILE) as f:
        return yaml.safe_load(f)["tasks"]


def _outcome_snippet():
    blocks = [c for c in _tasks()["idc:configure"]["cmds"] if isinstance(c, str) and "IDC_STATUS_FILE=" in c]
    assert len(blocks) == 1
    block = blocks[0]
    return block[block.index('IDC_STATUS_FILE="${IDC_STATUS_FILE'):]


def _render(snippet, task_vars):
    def fill(m):
        name, default = m.group(1), m.group(2)
        if name in task_vars:
            return task_vars[name]
        if name.startswith("C_"):
            return ""
        return default if default is not None else ""

    return TEMPLATE_VAR.sub(fill, snippet)


def _run(tmp_path, success, task_vars):
    status = tmp_path / "status"
    script = f"IDC_SUCCESS={'true' if success else 'false'}\n" + _render(_outcome_snippet(), task_vars)
    env = dict(os.environ, IDC_STATUS_FILE=str(status))
    r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    return r.returncode, status.read_text().split()[0]


def test_standalone_failure_exits_nonzero(tmp_path):
    assert _run(tmp_path, False, {}) == (1, "FAILED")


def test_failure_tolerated_when_not_strict(tmp_path):
    assert _run(tmp_path, False, {"IDC_STRICT": "false"}) == (0, "FAILED")


def test_success_exits_zero(tmp_path):
    assert _run(tmp_path, True, {}) == (0, "SUCCESS")


def test_post_install_calls_idc_configure_tolerantly():
    calls = [c for c in _tasks()["post-install"]["cmds"] if isinstance(c, dict) and c.get("task") == "idc:configure"]
    assert len(calls) == 1
    assert calls[0]["vars"]["IDC_STRICT"] == '{{.IDC_STRICT | default "false"}}'


def test_no_shell_env_default_left():
    # The old `${IDC_STRICT:-false}` made standalone runs tolerant by default.
    assert "${IDC_STRICT:-false}" not in _outcome_snippet()


@pytest.mark.skipif(not shutil.which("task"), reason="go-task not on PATH")
@pytest.mark.parametrize("strict,expect_fail", [(None, True), ("false", False)])
def test_go_task_exit_code(tmp_path, strict, expect_fail):
    """Real go-task semantics: a cmd exiting 1 makes `task` exit non-zero."""
    tf = tmp_path / "Taskfile.yaml"
    tf.write_text(
        "version: '3'\nsilent: true\ntasks:\n  t:\n    cmds:\n      - |\n"
        + "".join(f"        {line}\n" for line in ("IDC_SUCCESS=false\n" + _outcome_snippet()).splitlines())
    )
    args = ["task", "-t", str(tf), "t"] + ([f"IDC_STRICT={strict}"] if strict else [])
    env = dict(os.environ, IDC_STATUS_FILE=str(tmp_path / "status"))
    env.pop("IDC_STRICT", None)
    r = subprocess.run(args, env=env, capture_output=True, text=True, cwd=tmp_path)
    assert (r.returncode != 0) is expect_fail, r.stderr
