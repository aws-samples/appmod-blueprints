"""The Keycloak wait at the start of `idc:configure` must honour IDC_STRICT.

A slow Keycloak used to `exit 1` unconditionally, which aborted `task install`
(post-install passes IDC_STRICT=false) before ray:setup, setup-env and the OAP block.
Standalone `task idc:configure` stays strict by default.

The wait snippet is read verbatim from the Taskfile, go-task vars filled in, and run
with bash against a fake `curl` on PATH. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_idc_keycloak_wait.py -q
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


def _wait_snippet():
    blocks = [c for c in _tasks()["idc:configure"]["cmds"] if isinstance(c, str) and "KC_READY=false" in c]
    assert len(blocks) == 1
    return blocks[0]


def _render(snippet, task_vars):
    def fill(m):
        name, default = m.group(1), m.group(2)
        if name in task_vars:
            return task_vars[name]
        if name.startswith("C_"):
            return ""
        return default if default is not None else ""

    return TEMPLATE_VAR.sub(fill, snippet)


def _run(tmp_path, http_code, task_vars):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "curl"
    fake.write_text(f"#!/bin/sh\nprintf '{http_code}'\n")
    fake.chmod(0o755)
    status = tmp_path / "status"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", KC_WAIT_ATTEMPTS="2",
               KC_WAIT_INTERVAL="0", IDC_STATUS_FILE=str(status))
    tv = dict(task_vars, KEYCLOAK_DNS="kc.example.test")
    r = subprocess.run(["bash", "-c", _render(_wait_snippet(), tv)], env=env, capture_output=True, text=True)
    return r.returncode, (status.read_text() if status.exists() else ""), r.stdout


def test_unreachable_standalone_is_strict(tmp_path):
    rc, status, _ = _run(tmp_path, "404", {})
    assert rc == 1
    assert status.startswith("FAILED")


def test_unreachable_tolerated_when_not_strict(tmp_path):
    rc, status, out = _run(tmp_path, "404", {"IDC_STRICT": "false"})
    assert rc == 0
    assert status.startswith("FAILED") and "keycloak-unreachable" in status
    assert "task idc:configure" in out


def test_reachable_writes_no_status(tmp_path):
    rc, status, _ = _run(tmp_path, "200", {"IDC_STRICT": "false"})
    assert (rc, status) == (0, "")
