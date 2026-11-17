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
    order = ["task install:complete", "join cloudfront:attach", "task idc:configure", "task: wait-for-spokes", ":hub:pivot"]
    idx = [_index(REMOTE, n) for n in order]
    assert idx == sorted(idx), dict(zip(order, idx))
    line = REMOTE[_index(REMOTE, "task idc:configure")]
    assert "IDC_STRICT=false" in line


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


# ---------------------------------------------------------------- idc:configure never stops the pivot

IDC_WRAPPER = [c for c in REMOTE if "task idc:configure" in c][0]


def _run_wrapper(tmp_path, task_rc, status=None, skip="false"):
    (tmp_path / "bin").mkdir(exist_ok=True)
    f = tmp_path / "bin" / "task"
    body = "#!/bin/sh\n"
    if status:
        body += f'echo "{status}" > "$IDC_STATUS_FILE"\n'
    body += f"exit {task_rc}\n"
    f.write_text(body)
    f.chmod(0o755)
    sf = tmp_path / "idc-configure-status"
    block = IDC_WRAPPER.replace("/tmp/idc-configure-status", str(sf)).replace('{{.IDC_CONFIGURE_SKIP | default "false"}}', skip)
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", IDC_STATUS_FILE=str(sf))
    r = subprocess.run(["bash", "-c", "set -e\n" + block + "\necho AFTER"], env=env, capture_output=True, text=True, timeout=30)
    return r, (sf.read_text() if sf.exists() else "")


@pytest.mark.parametrize("rc,status,skip,want", [
    (1, None, "false", "FAILED rc=1"),          # early exit 1 (no domain, Keycloak down, pip, no credentials)
    (0, "SUCCESS 2026-11-16T00:00:00Z", "false", "SUCCESS"),
    (0, "FAILED 2026-11-16T00:00:00Z", "false", "FAILED"),  # tolerant failure inside the task
    (0, None, "true", "SKIPPED"),               # IDC_CONFIGURE_SKIP
    (0, None, "false", "UP-TO-DATE"),           # status: block says nothing to do
])
def test_idc_wrapper_never_fails_the_build_and_always_leaves_a_status(tmp_path, rc, status, skip, want):
    r, out = _run_wrapper(tmp_path, rc, status, skip)
    assert r.returncode == 0 and "AFTER" in r.stdout, r.stdout + r.stderr  # the pivot step after it still runs
    assert out.startswith(want), out


def test_idc_wrapper_clears_a_stale_status_file(tmp_path):
    sf = tmp_path / "idc-configure-status"
    sf.write_text("SUCCESS stale\n")
    r, out = _run_wrapper(tmp_path, 1, None, "false")
    assert out.startswith("FAILED rc=1"), out


# ---------------------------------------------------------------- credentials step of idc:configure

CRED = [c for c in IDC if "DEBUG: LAMBDA_ARN" in c][0]

FAKE_AWS_IDC = r"""#!/bin/sh
echo "aws $*" >> "$LOG"
case "$1 $2" in
  "cloudformation describe-stacks") case "$*" in *SharedRoleArn*) echo arn:aws:iam::000000000000:role/shared;; *) echo None;; esac ;;
  "lambda list-functions") [ "$FAKE_LAMBDA" = 1 ] && echo arn:aws:lambda:us-west-2:000000000000:function:kc || echo None ;;
  "lambda invoke") echo '{"ParameterName":"p"}' > "$LAST" ; echo "payload=$*" >> "$LOG" ;;
esac
exit 0
"""


def _run_cred(tmp_path, lambda_found, role_env):
    (tmp_path / "bin").mkdir(exist_ok=True)
    for n, body in (("aws", FAKE_AWS_IDC), ("curl", 'echo "curl $*" >> "$LOG"')):
        (tmp_path / "bin" / n).write_text(body if body.startswith("#!") else "#!/bin/sh\n" + body + "\n")
        (tmp_path / "bin" / n).chmod(0o755)
    block = CRED.replace("/tmp/", str(tmp_path) + "/").replace("{{.AWS_REGION}}", "us-west-2").replace("{{.RESOURCE_PREFIX}}", "acme")
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", LOG=str(tmp_path / "log"),
               LAST=str(tmp_path / "lambda-response.json"), FAKE_LAMBDA="1" if lambda_found else "0")
    env.pop("IDC_CONSOLE_ROLE_ARN", None)
    if role_env:
        env["IDC_CONSOLE_ROLE_ARN"] = role_env
    (tmp_path / "log").write_text("")
    r = subprocess.run(["bash", "-c", block], env=env, capture_output=True, text=True, timeout=30)
    return r, (tmp_path / "log").read_text()


def test_credentials_use_the_console_role_of_the_build(tmp_path):
    role = "arn:aws:iam::000000000000:role/idc-console"
    r, log = _run_cred(tmp_path, True, role)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"'RoleArn': '{role}'" in log or role in log.split("payload=")[1]
    assert "SharedRoleArn" not in log and "iam list-roles" not in log  # no lookup of the IDE role


def test_credentials_without_the_build_role_still_use_the_ide_role(tmp_path):
    r, log = _run_cred(tmp_path, True, None)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "role/shared" in log.split("payload=")[1]


def test_no_lambda_in_the_build_is_an_error_not_an_instance_profile_fallback(tmp_path):
    r, log = _run_cred(tmp_path, False, "arn:aws:iam::000000000000:role/idc-console")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "curl" not in log and "ssm put-parameter" not in log
