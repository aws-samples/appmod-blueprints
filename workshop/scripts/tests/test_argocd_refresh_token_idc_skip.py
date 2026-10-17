"""IDC_CONFIGURE_SKIP reaches the IDE: `setup-env` (workshop/Taskfile.yaml) writes it to
~/.bashrc.d/platform.sh, and the `argocd-refresh-token` shell function
(hack/.bashrc.d/ssm-setup-ide-logs.sh) then never runs its Identity Center fallback.

When the SSO token sign-in fails, that fallback runs scripts/configure_identity_center.py,
which re-points the account's single IAM Identity Center to this stack's Keycloak. On a
second stack (installed with IDC_CONFIGURE_SKIP=true) the sign-in fails because Identity
Center federates to the first stack's Keycloak, so the fallback would break that stack's SSO.
The self-paced template's IDE timer runs the function every 6h.

The function is sourced from the repo file and run with bash. `aws`, `kubectl`, `python3`
and `argocd` are fakes on PATH that record their calls. setup-env's cmd is read verbatim from
the Taskfile, its go-task variables filled in, and run with bash; one test also runs go-task
itself on a copy of the Taskfile (skipped if go-task, yq or jq is not on PATH). No AWS, no
network.

Run:  python -m pytest workshop/scripts/tests/test_argocd_refresh_token_idc_skip.py -q
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
FUNCTIONS = os.path.join(REPO, "hack", ".bashrc.d", "ssm-setup-ide-logs.sh")
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")
TEMPLATE_VAR = re.compile(r'\{\{\s*\.([A-Z0-9_]+)\s*(?:\|\s*default\s+"([^"]*)"\s*)?\}\}')
NOTICE = "IDC_CONFIGURE_SKIP=true: IDC-Keycloak federation not reconfigured, IAM Identity Center not touched."
FAKES = {
    "aws": """echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "eks describe-capability") echo "https://argocd-0123abcd.eks-capabilities.us-west-2.amazonaws.com" ;;
  "sso-admin list-instances") echo "arn:aws:sso:::instance/ssoins-1111111111111111" ;;
  "cloudfront list-distributions") echo "d111111abcdef8.cloudfront.net" ;;
  "grafana list-workspaces") echo "g-0123456789" ;;
  "grafana describe-workspace") echo "g-0123456789.grafana-workspace.us-west-2.amazonaws.com" ;;
  "secretsmanager get-secret-value")
    echo '{"user_password":"not-a-real-password","keycloak_admin_password":"not-a-real-admin","git_token":"glpat-not-a-real-token"}' ;;
  *) echo "unexpected aws call: $*" >&2; exit 1 ;;
esac""",
    "kubectl": """echo "kubectl $*" >> "$FAKE_LOG"
case "$*" in
  *"get secret keycloak-config "*) printf '%s' "$(printf not-a-real-admin | base64)" ;;
  *"get secret acme-hub-cluster "*) echo "d111111abcdef8.cloudfront.net" ;;
  *) echo "unexpected kubectl call: $*" >&2; exit 1 ;;
esac""",
    "python3": """echo "python3 ${1##*/} ${*:2}" >> "$FAKE_LOG"
case "${1##*/}" in
  argocd_token_automation.py)
    if [ -n "${FAKE_TOKEN:-}" ]; then echo "$FAKE_TOKEN"; else echo "Failed to retrieve token" >&2; exit 1; fi ;;
  configure_identity_center.py) echo "IDC configured" ;;
  *) echo "unexpected python3 call: $*" >&2; exit 1 ;;
esac""",
    "argocd": 'echo "argocd $1" >> "$FAKE_LOG"',
}
SETUP_ENV_VARS = {"C_OK": "", "C_RESET": "", "CF_DOMAIN": "d111111abcdef8.cloudfront.net",
                  "GIT_DOMAIN_VAR": "", "ARGOCD_URL": "https://argocd-0123abcd.example.com",
                  "USER_PASSWORD": "not-a-real-password", "KC_ADMIN_PASSWORD": "not-a-real-admin",
                  "AWS_REGION": "us-west-2", "AWS_ACCOUNT_ID": "111122223333",
                  "RESOURCE_PREFIX": "acme", "HUB_CLUSTER_NAME": "acme-hub"}
CONFIG = """aws: {region: us-west-2, accountId: "111122223333"}
hub: {clusterName: acme-hub}
domain: d111111abcdef8.cloudfront.net
resourcePrefix: acme
"""


def _env(tmp_path, **extra):
    bindir, home = tmp_path / "bin", tmp_path / "home"
    bindir.mkdir(exist_ok=True)
    (home / ".bashrc.d").mkdir(parents=True, exist_ok=True)
    for name, body in FAKES.items():
        (bindir / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
        (bindir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {k: v for k, v in os.environ.items() if k not in ("IDC_CONFIGURE_SKIP", "FAKE_TOKEN")}
    env.update(PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(home), FAKE_LOG=str(log),
               WORKSPACE_PATH=str(tmp_path), WORKING_REPO="repo", RESOURCE_PREFIX="acme",
               AWS_REGION="us-west-2", USER1_PASSWORD="not-the-right-password", **extra)
    return env, log, home / ".bashrc.d" / "platform.sh"


def _bash(tmp_path, script, env):
    (tmp_path / "run.sh").write_text(script)
    return subprocess.run(["bash", str(tmp_path / "run.sh")], env=env, capture_output=True,
                          text=True, timeout=60)


def _refresh(tmp_path, preamble="", **extra):
    """Run `argocd-refresh-token` in a fresh bash; returns (result, recorded calls)."""
    env, log, _ = _env(tmp_path, **extra)
    res = _bash(tmp_path, f'{preamble}\nsource "{FUNCTIONS}"\nargocd-refresh-token\n', env)
    return res, log.read_text().splitlines()


def _idc_calls(calls):
    return [c for c in calls if c.startswith(("aws sso-admin", "aws identitystore", "kubectl"))
            or "configure_identity_center.py" in c]


def test_knob_skips_the_identity_center_fallback(tmp_path):
    res, calls = _refresh(tmp_path, IDC_CONFIGURE_SKIP="true")
    assert res.returncode == 1, res.stderr
    # it still tries a token, once, and touches nothing of Identity Center
    assert sum("argocd_token_automation.py" in c for c in calls) == 1, calls
    assert _idc_calls(calls) == [], calls
    assert NOTICE in res.stderr and "set USER1_PASSWORD" in res.stderr, res.stderr
    assert "Running IDC-Keycloak federation setup" not in res.stderr


def test_knob_still_gets_a_token(tmp_path):
    res, calls = _refresh(tmp_path, IDC_CONFIGURE_SKIP="true", FAKE_TOKEN="not-a-real-token")
    assert res.returncode == 0, res.stderr
    assert "ArgoCD token refreshed" in res.stdout
    assert _idc_calls(calls) == [] and NOTICE not in res.stderr, (calls, res.stderr)


@pytest.mark.parametrize("knob", [None, "false"])
def test_without_knob_the_fallback_still_configures_identity_center(tmp_path, knob):
    extra = {"IDC_CONFIGURE_SKIP": knob} if knob else {}
    res, calls = _refresh(tmp_path, **extra)
    assert res.returncode == 1, res.stderr  # the fake's retry fails too
    assert "aws sso-admin list-instances --query Instances[0].InstanceArn --output text" in calls
    (idc,) = [c for c in calls if "configure_identity_center.py" in c]
    assert "--instance-id 1111111111111111" in idc and "--keycloak-dns d111111abcdef8.cloudfront.net" in idc
    assert sum("argocd_token_automation.py" in c for c in calls) == 2, calls
    assert "Running IDC-Keycloak federation setup" in res.stderr and NOTICE not in res.stderr


def _setup_env(tmp_path, **task_vars):
    """setup-env's cmd, verbatim from the Taskfile, with its go-task variables filled in."""
    (block,) = yaml.safe_load(open(TASKFILE))["tasks"]["setup-env"]["cmds"]
    values = dict(SETUP_ENV_VARS, **task_vars)

    def fill(m):
        name, default = m.group(1), m.group(2)
        return values[name] if name in values else (default if default is not None else "")

    script = TEMPLATE_VAR.sub(fill, block)
    assert "{{" not in script, re.findall(r"\{\{[^}]*\}\}", script)
    env, _, platform_sh = _env(tmp_path)
    res = _bash(tmp_path, script, env)
    assert res.returncode == 0, res.stderr
    return platform_sh.read_text()


def test_setup_env_persists_the_knob_for_the_ide_shell(tmp_path):
    out = _setup_env(tmp_path, IDC_CONFIGURE_SKIP="true")
    assert re.findall(r"^export IDC_CONFIGURE_SKIP=.*$", out, re.M) == ['export IDC_CONFIGURE_SKIP="true"']
    out = _setup_env(tmp_path, IDC_CONFIGURE_SKIP="true")  # a re-run keeps one line
    assert out.count("IDC_CONFIGURE_SKIP") == 1
    # ...so a new IDE shell (or the template's token timer, which sources platform.sh) skips
    res, calls = _refresh(tmp_path, preamble='source "$HOME/.bashrc.d/platform.sh"')
    assert res.returncode == 1 and _idc_calls(calls) == [] and NOTICE in res.stderr, (calls, res.stderr)


@pytest.mark.parametrize("knob", [None, "false"])
def test_setup_env_without_knob_writes_nothing(tmp_path, knob):
    out = _setup_env(tmp_path, **({"IDC_CONFIGURE_SKIP": knob} if knob else {}))
    assert "export USER1_PASSWORD=" in out and "IDC_CONFIGURE_SKIP" not in out


@pytest.mark.skipif(not (TASK and shutil.which("yq") and shutil.which("jq")),
                    reason="needs go-task, yq and jq on PATH")
def test_setup_env_persists_the_knob_under_go_task(tmp_path):
    ws = tmp_path / "workshop"
    ws.mkdir()
    shutil.copy(TASKFILE, ws / "Taskfile.yaml")
    (tmp_path / "config.local.yaml").write_text(CONFIG)
    for args, extra, persisted in ((["setup-env", "IDC_CONFIGURE_SKIP=true"], {}, True),  # CLI form
                                   (["setup-env"], {"IDC_CONFIGURE_SKIP": "true"}, True),  # env form
                                   (["setup-env"], {}, False)):
        env, _, platform_sh = _env(tmp_path, **extra)
        if platform_sh.exists():
            platform_sh.unlink()
        res = subprocess.run([TASK, "-d", str(ws), *args], env=env, capture_output=True,
                             text=True, timeout=120)
        assert res.returncode == 0, res.stdout + res.stderr
        out = platform_sh.read_text()
        assert "export USER1_PASSWORD=" in out, out
        assert ('export IDC_CONFIGURE_SKIP="true"' in out) == persisted, (args, extra)
