"""Option B (v0.5): `idc:configure` (Identity Center SAML + SCIM through Playwright/Chromium) runs
in the CodeBuild install under the install role, so the IDE role needs no sso/identitystore right.

Pins, without AWS or network:
* install:remote runs idc:configure after the CloudFront join (Keycloak is reachable) and before the
  pivot, tolerant (IDC_STRICT=false: the status file says what happened); install:ide does not run it;
* idc:configure can run as root in a build container: no bare `sudo`, the console role comes from
  IDC_CONSOLE_ROLE_ARN when the build sets it, Lambda failure is not hidden;
* the Chromium system-deps helper of the idc package has no bare sudo.

Run:  python -m pytest workshop/scripts/tests/test_idc_in_build.py -q
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WS = yaml.safe_load(open(os.path.join(REPO, "workshop", "Taskfile.yaml")))["tasks"]


def _flat(cmds):
    out = []
    for c in cmds:
        if isinstance(c, str):
            out.append(c)
        elif "task" in c:
            out.append("task: " + c["task"] + " " + str(c.get("vars", "")))
        else:
            out.append(c.get("cmd", ""))
    return out


def _index(lines, needle):
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    assert hits, needle
    return hits[0]


REMOTE = _flat(WS["install:remote"]["cmds"])
IDE = _flat(WS["install:ide"]["cmds"])
IDC = _flat(WS["idc:configure"]["cmds"])


def test_remote_runs_idc_after_keycloak_and_before_the_pivot():
    order = ["task install:complete", "join cloudfront:attach", "task: idc:configure", "task: wait-for-spokes", ":hub:pivot"]
    idx = [_index(REMOTE, n) for n in order]
    assert idx == sorted(idx), dict(zip(order, idx))
    line = REMOTE[_index(REMOTE, "task: idc:configure")]
    assert "IDC_STRICT" in line and "false" in line


def test_remote_records_the_idc_step():
    assert any("step=idc:configure" in ln for ln in REMOTE)


def test_ide_half_does_not_configure_identity_center():
    text = "\n".join(IDE)
    assert "idc" not in text and "post-install" not in text


def test_default_install_still_runs_post_install():
    assert "post-install" in "\n".join(_flat(WS["install"]["cmds"]))


def _yum_cmd():
    (c,) = [c for c in IDC if "yum install" in c]
    return c


def test_chromium_deps_install_works_as_root_without_sudo(tmp_path):
    (tmp_path / "bin").mkdir()
    for n, body in (("yum", 'echo "yum $*" >> "$LOG"'), ("id", 'echo 0')):
        (tmp_path / "bin" / n).write_text("#!/bin/sh\n" + body + "\n")
        (tmp_path / "bin" / n).chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:/usr/bin:/bin", LOG=str(tmp_path / "log"))
    r = subprocess.run(["bash", "-c", _yum_cmd()], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "yum install -y atk" in (tmp_path / "log").read_text() and "mesa-libgbm" in (tmp_path / "log").read_text()


def test_chromium_deps_install_still_uses_sudo_for_a_normal_user(tmp_path):
    (tmp_path / "bin").mkdir()
    for n, body in (("sudo", 'echo "sudo $*" >> "$LOG"'), ("yum", 'echo "yum $*" >> "$LOG"'), ("id", 'echo 1000')):
        (tmp_path / "bin" / n).write_text("#!/bin/sh\n" + body + "\n")
        (tmp_path / "bin" / n).chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:/usr/bin:/bin", LOG=str(tmp_path / "log"))
    subprocess.run(["bash", "-c", _yum_cmd()], env=env, check=True, timeout=30)
    assert "sudo yum install -y atk" in (tmp_path / "log").read_text()


def test_pip_goes_through_the_interpreter_and_is_not_silenced():
    (c,) = [c for c in IDC if "playwright boto3" in c]
    assert c.startswith("python3 -m pip install") and "2>/dev/null" not in c


def test_console_role_comes_from_the_build_when_set():
    big = "\n".join(IDC)
    assert 'IDC_CONSOLE_ROLE_ARN' in big
    # the SharedRole lookup stays as the fallback for the inline install
    assert "SharedRoleArn" in big


def test_idc_package_has_no_bare_sudo():
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    try:
        import idc.constants as c
    finally:
        sys.path.pop(0)
    real = os.geteuid
    try:
        os.geteuid = lambda: 0
        assert c.privilege_prefix() == []
        os.geteuid = lambda: 1000
        assert c.privilege_prefix() == ["sudo"]
    finally:
        os.geteuid = real
    src = open(os.path.join(REPO, "scripts", "idc", "browser.py")).read()
    assert '["sudo"' not in src and "privilege_prefix()" in src
