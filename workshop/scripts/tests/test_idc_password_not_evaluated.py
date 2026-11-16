"""idc:configure must hand the Keycloak admin password to configure_identity_center.py as data.

The password comes from the <hub>/keycloak secret. If go-task templated it into the script
text, a `$(...)` or backticks in the value would run as the role of the caller (the install
role in the CodeBuild install). The task passes it through `env:` instead, and the script reads
KC_ADMIN_PASSWORD, so the value is not on the command line either.

The real go-task runs the real `idc:configure` cmd that calls the script, on a copy of the
Taskfile (status and the network/Lambda/pip steps removed). `aws` and `curl` are fakes and
configure_identity_center.py is a stand-in that records its argv. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_idc_password_not_evaluated.py -q
"""
import json
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")

pytestmark = pytest.mark.skipif(not (TASK and shutil.which("yq") and shutil.which("jq")),
                                reason="needs go-task, yq and jq on PATH")

FAKE_AWS = """#!/usr/bin/env bash
case "$1 $2" in
  "secretsmanager get-secret-value") cat "$FAKE_KC_SECRET_FILE" ;;
  *) echo "" ;;
esac
"""
FAKE_CURL = "#!/usr/bin/env bash\necho 200\n"
STAND_IN = """import json, os, sys
json.dump({"argv": sys.argv[1:], "env": os.environ.get("KC_ADMIN_PASSWORD")}, open(sys.argv[0] + ".argv", "w"))
"""
CONFIG = """aws: {region: us-west-2, accountId: "111122223333"}
hub: {clusterName: acme-hub}
identityCenter: {instanceArn: "arn:aws:sso:::instance/ssoins-1111111111111111", region: us-west-2, adminGroupId: g-1}
gitUsername: user1
domain: kc.example.invalid
"""


def _run(tmp_path, password):
    canary = tmp_path / "PWNED"
    doc = yaml.safe_load(open(TASKFILE))
    task = doc["tasks"]["idc:configure"]
    task.pop("status")
    # Only the real cmd that runs the script (Keycloak/SAML probes answered by the fake curl).
    (cmd,) = [c for c in task["cmds"] if isinstance(c, str) and "configure_identity_center.py" in c]
    task["cmds"] = [cmd]
    ws = tmp_path / "workshop"
    ws.mkdir()
    (ws / "Taskfile.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    (tmp_path / "config.local.yaml").write_text(CONFIG)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "configure_identity_center.py").write_text(STAND_IN)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("aws", FAKE_AWS), ("curl", FAKE_CURL), ("sleep", "#!/bin/sh\nexit 0\n")):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"keycloak_admin_password": password.replace("CANARY", str(canary))}))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_KC_SECRET_FILE=str(secret),
               IDC_STATUS_FILE=str(tmp_path / "status"))
    for k in ("IDC_CONFIGURE_SKIP", "KC_ADMIN_PASSWORD"):
        env.pop(k, None)
    res = subprocess.run([TASK, "-d", str(ws), "idc:configure"], env=env, capture_output=True,
                         text=True, timeout=120)
    argv_file = tmp_path / "scripts" / "configure_identity_center.py.argv"
    argv = json.loads(argv_file.read_text()) if argv_file.exists() else None
    return res, argv, canary


@pytest.mark.parametrize("password", [
    "a$(touch CANARY)b",
    "a`touch CANARY`b",
    "q\"uo'te $HOME ${PATH} \\ end",
])
def test_password_reaches_the_script_verbatim_and_is_never_run(tmp_path, password):
    res, argv, canary = _run(tmp_path, password)
    assert res.returncode == 0, res.stdout + res.stderr
    assert not canary.exists(), "the password was evaluated by the shell"
    want = password.replace("CANARY", str(canary))
    assert argv["env"] == want, argv
    # never on the command line either (visible to every process on the host)
    assert not [a for a in argv["argv"] if "keycloak-admin-password" in a or want in a], argv


def test_the_script_text_never_holds_the_password():
    task = yaml.safe_load(open(TASKFILE))["tasks"]["idc:configure"]
    assert task["env"]["KC_ADMIN_PASSWORD"] == "{{.KC_ADMIN_PASSWORD}}"
    for c in task["cmds"]:
        text = c if isinstance(c, str) else c.get("cmd", "")
        assert "{{.KC_ADMIN_PASSWORD}}" not in text


def test_script_reads_the_password_from_the_environment():
    src = open(os.path.join(REPO, "scripts", "configure_identity_center.py")).read()
    assert 'os.environ.get("KC_ADMIN_PASSWORD"' in src
    assert 'add_argument("--keycloak-admin-password", required=True)' not in src


# ---------------------------------------------------------------- the real script reads the variable

FAKE_ORCH = """import json, os
async def configure_identity_center(**kw):
    json.dump(kw, open(os.environ["FAKE_ORCH_OUT"], "w"))
    return {"ok": True}
"""


def _real_script(tmp_path, env_pw, flag_pw=None):
    pytest.importorskip("tenacity")  # the script pip-installs it otherwise
    pytest.importorskip("urllib3")
    d = tmp_path / "s"
    (d / "idc").mkdir(parents=True)
    shutil.copy(os.path.join(REPO, "scripts", "configure_identity_center.py"), d / "configure_identity_center.py")
    (d / "idc" / "__init__.py").write_text("")
    (d / "idc" / "constants.py").write_text("SCIM_DATA_FILE = '/nonexistent'\n")
    (d / "idc" / "orchestrator.py").write_text(FAKE_ORCH)
    out = tmp_path / "kw.json"
    env = {k: v for k, v in os.environ.items() if k != "KC_ADMIN_PASSWORD"}
    env["FAKE_ORCH_OUT"] = str(out)
    if env_pw is not None:
        env["KC_ADMIN_PASSWORD"] = env_pw
    args = ["python3", str(d / "configure_identity_center.py"), "--region", "r", "--instance-id", "i",
            "--keycloak-dns", "kc.example.invalid"]
    if flag_pw is not None:
        args.append(f"--keycloak-admin-password={flag_pw}")
    r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    return r, (json.loads(out.read_text()) if out.exists() else None)


def test_real_script_uses_the_environment_variable(tmp_path):
    r, kw = _real_script(tmp_path, "from-env $(x)")
    assert r.returncode == 0, r.stderr
    assert kw["keycloak_admin_password"] == "from-env $(x)"


def test_real_script_flag_still_wins_for_manual_runs(tmp_path):
    r, kw = _real_script(tmp_path, "from-env", flag_pw="from-flag")
    assert r.returncode == 0 and kw["keycloak_admin_password"] == "from-flag", r.stderr


@pytest.mark.parametrize("env_pw", [None, ""])
def test_real_script_refuses_an_empty_password(tmp_path, env_pw):
    r, kw = _real_script(tmp_path, env_pw)
    assert r.returncode == 1 and kw is None
    assert "no Keycloak admin password" in r.stderr


def test_no_caller_puts_the_password_on_the_command_line():
    for rel in ("hack/.bashrc.d/ssm-setup-ide-logs.sh", "workshop/Taskfile.yaml"):
        assert "--keycloak-admin-password" not in open(os.path.join(REPO, rel)).read(), rel
