"""Hermetic tests for IDC_CONFIGURE_SKIP (workshop/Taskfile.yaml): with the knob set,
`idc:configure` is skipped before any AWS call, so a second stack never re-points the
account's single IAM Identity Center; without it, the task still runs exactly when the git
user is missing from the identity store.

The task's `status:` block (go-task skips the task when it exits 0) and the `post-install`
notice are read verbatim from the Taskfile, their go-task variables are filled in, and they
run with bash. `aws` is a fake that records its calls. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_idc_configure_skip.py -q
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
FAKE_AWS = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
case "$1 $2" in
  "sso-admin list-instances") echo "d-1111111111" ;;
  "identitystore list-users") echo "${FAKE_IDC_USER_ID:-None}" ;;
  *) echo "unexpected aws call: $*" >&2; exit 1 ;;
esac
"""
TASK_VARS = {"AWS_REGION": "us-west-2", "GIT_USERNAME": "user1", "C_INFO": "", "C_RESET": "",
             "IDC_INSTANCE_ARN": "arn:aws:sso:::instance/ssoins-1111111111111111"}


def _render(block, **task_vars):
    values = dict(TASK_VARS, **task_vars)

    def fill(m):
        name, default = m.group(1), m.group(2)
        return values[name] if name in values else (default if default is not None else "")

    out = TEMPLATE_VAR.sub(fill, block)
    assert "{{" not in out, re.findall(r"\{\{[^}]*\}\}", out)
    return out


def _run(tmp_path, script, user_id=None):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS)
    (bindir / "aws").chmod(0o755)
    log = tmp_path / "aws.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log))
    if user_id:
        env["FAKE_IDC_USER_ID"] = user_id
    (tmp_path / "run.sh").write_text(script)
    res = subprocess.run(["bash", str(tmp_path / "run.sh")], env=env, capture_output=True,
                         text=True, timeout=60)
    return res.returncode, res.stdout, log.read_text().splitlines()


def _tasks():
    return yaml.safe_load(open(TASKFILE))["tasks"]


def _status(tmp_path, user_id=None, **task_vars):
    (block,) = _tasks()["idc:configure"]["status"]
    return _run(tmp_path, _render(block, **task_vars), user_id)


def test_skip_knob_never_calls_aws(tmp_path):
    # the git user is NOT in the identity store, so without the knob the task would run
    rc, _, calls = _status(tmp_path, IDC_CONFIGURE_SKIP="true")
    assert (rc, calls) == (0, [])
    # default unchanged: missing user -> run (rc 1); present user -> skip (rc 0)
    rc, _, calls = _status(tmp_path)
    assert rc == 1 and len(calls) == 2
    rc, _, _ = _status(tmp_path, user_id="11111111-2222-3333-4444-555555555555")
    assert rc == 0
    rc, _, _ = _status(tmp_path, IDC_CONFIGURE_SKIP="false")
    assert rc == 1


def test_post_install_says_why_idc_is_skipped(tmp_path):
    notices = [c for c in _tasks()["post-install"]["cmds"]
               if isinstance(c, str) and "IDC_CONFIGURE_SKIP" in c]
    assert len(notices) == 1
    _, out, _ = _run(tmp_path, "set -euo pipefail\n" + _render(notices[0], IDC_CONFIGURE_SKIP="true"))
    assert "IAM Identity Center not touched" in out
    rc, out, _ = _run(tmp_path, "set -euo pipefail\n" + _render(notices[0]))
    assert (rc, out) == (0, "")
