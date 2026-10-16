"""Hermetic tests for IDC_CONFIGURE_SKIP (workshop/Taskfile.yaml): with the knob set,
`idc:configure` is skipped without any AWS call, so a second stack never re-points the
account's single IAM Identity Center; without it, the task still runs exactly when the git
user is missing from the identity store.

The task's `status:` block (go-task skips the task when it exits 0) and the `post-install`
notice are read verbatim from the Taskfile, their go-task variables are filled in, and they
run with bash. go-task resolves a task's `vars:` before its `status:`, so one test also runs
go-task itself on a copy of the Taskfile (skipped if go-task is not on PATH). `aws` is a fake
that records its calls. No AWS, no network.

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
TASK = shutil.which("task")
TEMPLATE_VAR = re.compile(r'\{\{\s*\.([A-Z0-9_]+)\s*(?:\|\s*default\s+"([^"]*)"\s*)?\}\}')
FAKE_AWS = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
case "$1 $2" in
  "sso-admin list-instances") echo "d-1111111111" ;;
  "identitystore list-users") echo "${FAKE_IDC_USER_ID:-None}" ;;
  "secretsmanager get-secret-value")
    if [ -z "${FAKE_KC_SECRET:-}" ]; then
      echo "An error occurred (ResourceNotFoundException) when calling the GetSecretValue operation" >&2
      exit 254
    fi
    echo "$FAKE_KC_SECRET" ;;
  *) echo "unexpected aws call: $*" >&2; exit 1 ;;
esac
"""
TASK_VARS = {"AWS_REGION": "us-west-2", "GIT_USERNAME": "user1", "C_INFO": "", "C_RESET": "",
             "IDC_INSTANCE_ARN": "arn:aws:sso:::instance/ssoins-1111111111111111"}
# config.local.yaml for the go-task runs. No domain: if idc:configure's cmds ever ran, the
# first one would exit 1 on the empty KEYCLOAK_DNS before any network call.
CONFIG = """aws: {region: us-west-2, accountId: "111122223333"}
hub: {clusterName: acme-hub}
identityCenter: {instanceArn: "arn:aws:sso:::instance/ssoins-1111111111111111", region: us-west-2, adminGroupId: g-1}
gitUsername: user1
"""


def _render(block, **task_vars):
    values = dict(TASK_VARS, **task_vars)

    def fill(m):
        name, default = m.group(1), m.group(2)
        return values[name] if name in values else (default if default is not None else "")

    out = TEMPLATE_VAR.sub(fill, block)
    assert "{{" not in out, re.findall(r"\{\{[^}]*\}\}", out)
    return out


def _fake_env(tmp_path, user_id=None):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS)
    (bindir / "aws").chmod(0o755)
    log = tmp_path / "aws.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log))
    env.pop("IDC_CONFIGURE_SKIP", None)
    if user_id:
        env["FAKE_IDC_USER_ID"] = user_id
    return env, log


def _run(tmp_path, script, user_id=None):
    env, log = _fake_env(tmp_path, user_id)
    (tmp_path / "run.sh").write_text(script)
    res = subprocess.run(["bash", str(tmp_path / "run.sh")], env=env, capture_output=True,
                         text=True, timeout=60)
    return res.returncode, res.stdout, log.read_text().splitlines()


def _tasks():
    return yaml.safe_load(open(TASKFILE))["tasks"]


def _gotask(tmp_path, *args, taskfile=None, **env_vars):
    """go-task on a copy of the Taskfile in <tmp>/workshop, so REPO is <tmp> and its
    config.local.yaml is CONFIG. go-task resolves the global and task vars itself."""
    ws = tmp_path / "workshop"
    ws.mkdir(exist_ok=True)
    (ws / "Taskfile.yaml").write_text(taskfile or open(TASKFILE).read())
    (tmp_path / "config.local.yaml").write_text(CONFIG)
    env, log = _fake_env(tmp_path)
    env.update(env_vars)
    res = subprocess.run([TASK, "-d", str(ws), *args], env=env, capture_output=True,
                         text=True, timeout=120)
    return res, [c.split()[:2] for c in log.read_text().splitlines()]


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


@pytest.mark.skipif(not (TASK and shutil.which("yq") and shutil.which("jq")),
                    reason="needs go-task, yq and jq on PATH")
def test_skip_knob_makes_no_aws_call_under_go_task(tmp_path):
    # The fake's secret lookup fails, as for a stack whose keycloak secret is missing.
    for args, env in ((["idc:configure", "IDC_CONFIGURE_SKIP=true"], {}),
                      (["post-install"], {"IDC_CONFIGURE_SKIP": "true"}),
                      (["post-install", "IDC_CONFIGURE_SKIP=true"], {})):
        res, calls = _gotask(tmp_path, *args, **env)
        assert (res.returncode, calls) == (0, []), (args, env, res.stdout + res.stderr)
        if args[0] == "post-install":
            assert "IAM Identity Center not touched" in res.stdout, res.stdout
    # Without the knob go-task still reads the secret, before the status check decides.
    res, calls = _gotask(tmp_path, "--status", "idc:configure")
    assert res.returncode != 0, res.stdout + res.stderr  # git user missing -> the task would run
    assert calls == [["secretsmanager", "get-secret-value"], ["sso-admin", "list-instances"],
                     ["identitystore", "list-users"]], calls
    # ...and KC_ADMIN_PASSWORD still resolves to the password. A copy whose idc:configure
    # only prints the var (the real vars block, no status, no other cmds):
    doc = yaml.safe_load(open(TASKFILE))
    task = doc["tasks"]["idc:configure"]
    task.pop("status")
    task["cmds"] = ['printf "[%s]" "{{.KC_ADMIN_PASSWORD}}"']
    printer = yaml.safe_dump(doc, sort_keys=False)
    secret = '{"keycloak_admin_password":"not-a-real-password"}'
    res, calls = _gotask(tmp_path, "idc:configure", taskfile=printer, FAKE_KC_SECRET=secret)
    assert (res.returncode, res.stdout, calls) == (0, "[not-a-real-password]",
                                                   [["secretsmanager", "get-secret-value"]])
    res, calls = _gotask(tmp_path, "idc:configure", "IDC_CONFIGURE_SKIP=true", taskfile=printer,
                         FAKE_KC_SECRET=secret)
    assert (res.returncode, res.stdout, calls) == (0, "[]", [])


# Answers every call idc:setup can make, so the run without the knob gets through its
# vars and into the cmds. The test only reads which services were called.
FAKE_AWS_SETUP = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
case "$1 $2" in
  "sts get-caller-identity") echo "arn:aws:sts::111122223333:assumed-role/Admin/x" ;;
  "sso-admin list-instances") echo "d-1111111111" ;;
  "identitystore list-groups") echo "g-1" ;;
  "identitystore list-users") echo "u-1" ;;
  "identitystore "*) echo "x-1" ;;
  *) echo "" ;;
esac
"""
IDC_SERVICES = ("sso-admin", "identitystore", "sso")


@pytest.mark.skipif(not (TASK and shutil.which("yq")), reason="needs go-task and yq on PATH")
@pytest.mark.parametrize("form", ["env", "cli"])
def test_kind_kro_ack_idc_setup_honours_the_knob(tmp_path, form):
    """kind-kro-ack's manual idc:setup writes groups, users and memberships into the same
    shared Identity Center. With the knob it must do nothing and call no IdC API, in its
    task vars as well as its cmds (go-task resolves task vars before status:)."""
    # A copy of the repo layout go-task needs: the root Taskfile (which includes the
    # providers), cluster-providers/ and the addon registry, plus our config.local.yaml.
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(os.path.join(REPO, "Taskfile.yaml"), root / "Taskfile.yaml")
    shutil.copytree(os.path.join(REPO, "cluster-providers"), root / "cluster-providers")
    shutil.copytree(os.path.join(REPO, "gitops", "addons", "registry"), root / "gitops" / "addons" / "registry")
    (root / "config.local.yaml").write_text(CONFIG.replace("adminGroupId: g-1", 'adminGroupId: ""'))
    env, log = _fake_env(tmp_path)
    (tmp_path / "bin" / "aws").write_text(FAKE_AWS_SETUP)

    def run(*extra, **env_vars):
        log.write_text("")
        e = dict(env, **env_vars)
        # As the workshop runs it: from the repo root, through the kind-kro-ack include.
        res = subprocess.run([TASK, "-d", str(root), "kind-kro-ack:idc:setup", *extra],
                             env=e, capture_output=True, text=True, timeout=120)
        return res, [c.split()[0] for c in log.read_text().splitlines()]

    if form == "env":
        res, svcs = run(IDC_CONFIGURE_SKIP="true")
    else:
        res, svcs = run("IDC_CONFIGURE_SKIP=true")
    assert res.returncode == 0, res.stderr
    assert not [s for s in svcs if s in IDC_SERVICES], svcs
    assert "idc:setup skipped" in res.stdout, res.stdout  # the operator can see the knob took effect

    res, svcs = run()  # no knob: it still talks to Identity Center
    assert "identitystore" in svcs, (svcs, res.stderr[-400:])
