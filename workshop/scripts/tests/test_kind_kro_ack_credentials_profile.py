"""#1259: kind-kro-ack ACK credentials and the shipped `aws.profile: "default"`.

config.yaml ships `profile: "default"`. credentials:refresh used to treat it like "no
profile" and, on any EC2 host, write the host's instance role into the ACK secret, even
when that role is in another account than aws.accountId. ACK then provisioned in the
wrong account, and check-and-refresh (validity only) kept that secret across re-runs.

What these tests pin, with fakes only (fake `aws`, `curl`, `kubectl` on PATH; no AWS,
no network), running the REAL Taskfile blocks under go-task's own shell:

1. profile "default", configured locally: the instance role is kept when it is on
   aws.accountId (workshop IDE, unchanged), the default profile is used when it is not.
2. a named profile: used as before; refused when it is on another account.
3. no profile: IMDS stays the deliberate source, but never for another account.
4. check-and-refresh refreshes a valid secret of another account, and that failure
   is not swallowed; the expired case keeps its best-effort behaviour.
5. kind-kro-ack exports AWS_PROFILE / AWS_CONFIG_FILE exactly like kind-crossplane
   (README "AWS credential resolution"), and the env a kind-kro-ack task sees is the
   same as a kind-crossplane task sees (rendered with the real root Taskfile).
6. shellcheck on the two blocks (when shellcheck is on PATH).

Run:  python -m pytest workshop/scripts/tests/test_kind_kro_ack_credentials_profile.py -q
"""
import base64
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
KRO = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
XP = os.path.join(REPO, "cluster-providers", "kind-crossplane", "Taskfile.yaml")
TASK = shutil.which("task")
WANT = "111111111111"
OTHER = "222222222222"
needs_task = pytest.mark.skipif(not TASK, reason="go-task not on PATH")
needs_tools = pytest.mark.skipif(not (shutil.which("yq") and shutil.which("jq")), reason="yq/jq not on PATH")


def tasks(path):
    with open(path) as f:
        return yaml.safe_load(f)


def block(task, index):
    cmd = tasks(KRO)["tasks"][task]["cmds"][index]
    return cmd["cmd"] if isinstance(cmd, dict) else cmd


# Credentials are fake strings that carry their account: AKI-<account>-<source>.
FAKE_AWS = r"""#!/bin/sh
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "configure list-profiles")
    for p in $FAKE_PROFILES; do echo "${p%%:*}"; done; exit 0 ;;
  "configure export-credentials")
    shift 2
    while [ $# -gt 0 ]; do [ "$1" = "--profile" ] && NAME=$2; shift; done
    for p in $FAKE_PROFILES; do
      if [ "${p%%:*}" = "$NAME" ]; then
        A=${p#*:}
        echo "AWS_ACCESS_KEY_ID=AKI-$A-$NAME"; echo "AWS_SECRET_ACCESS_KEY=SAK"; echo "AWS_SESSION_TOKEN=ST"
        exit 0
      fi
    done
    echo "The config profile ($NAME) could not be found" >&2; exit 255 ;;
  "sts get-caller-identity")
    [ -n "${AWS_PROFILE:-}${AWS_DEFAULT_PROFILE:-}" ] && { echo "profile env leaked" >&2; exit 254; }
    case "${AWS_ACCESS_KEY_ID:-}" in
      AKI-EXPIRED*) echo "An error occurred (ExpiredToken)" >&2; exit 254 ;;
      AKI-*) A=${AWS_ACCESS_KEY_ID#AKI-}; A=${A%%-*} ;;
      *) echo "Unable to locate credentials" >&2; exit 253 ;;
    esac
    case "$*" in *"--query Account"*) echo "$A" ;; *) printf '%s\tarn:aws:iam::%s:role/r\tAID\n' "$A" "$A" ;; esac
    exit 0 ;;
esac
echo "unexpected aws call: $*" >&2; exit 2
"""

FAKE_CURL = r"""#!/bin/sh
echo "curl $*" >> "$FAKE_LOG"
[ -n "${FAKE_IMDS_ACCOUNT:-}" ] || exit 7
case "$*" in
  *api/token*) echo "tok" ;;
  *security-credentials/role*) printf '{"AccessKeyId":"AKI-%s-imds","SecretAccessKey":"SAK","Token":"ST"}\n' "$FAKE_IMDS_ACCOUNT" ;;
  *security-credentials/*) echo "role" ;;
esac
"""

FAKE_KUBECTL = r"""#!/bin/sh
echo "kubectl $*" >> "$FAKE_LOG"
[ -n "${FAKE_SECRET_B64:-}" ] || exit 1
case "$*" in *jsonpath*) printf '%s' "$FAKE_SECRET_B64" ;; esac
exit 0
"""


def harness(tmp_path, profile):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", FAKE_AWS), ("curl", FAKE_CURL), ("kubectl", FAKE_KUBECTL)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    (tmp_path / "private").mkdir()
    cfg = tmp_path / "config.local.yaml"
    lines = ["aws:", f'  accountId: "{WANT}"', '  region: "us-west-2"']
    if profile is not None:
        lines.append(f'  profile: "{profile}"')
    cfg.write_text("\n".join(lines) + "\n")
    tf = {
        "version": "3",
        "set": ["errexit", "nounset", "pipefail"],
        "silent": True,
        "vars": {
            "CONFIG_FILE": str(cfg), "AWS_ACCOUNT_ID": WANT, "AWS_REGION": "us-west-2",
            "ACK_NAMESPACE": "ack-system",
            **{c: "" for c in ("C_INFO", "C_OK", "C_STEP", "C_ERR", "C_WARN", "C_RESET")},
        },
        "tasks": {
            "under-test-refresh": {"cmds": [block("credentials:refresh", 1)]},
            "under-test-check": {"cmds": [block("credentials:check-and-refresh", 0)]},
            # stub the nested `task credentials:refresh` of check-and-refresh
            "credentials:refresh": {"cmds": ['echo REFRESH-CALLED; exit "${FAKE_REFRESH_RC:-0}"']},
        },
    }
    (tmp_path / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    return bin_dir


def run(tmp_path, bin_dir, task, profiles="", imds=None, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "calls.log"),
               FAKE_PROFILES=profiles, FAKE_IMDS_ACCOUNT=imds or "",
               AWS_PROFILE="default", AWS_DEFAULT_PROFILE="default")  # as exported by env:
    env.update(extra)
    r = subprocess.run([TASK, "-d", str(tmp_path), task], env=env, capture_output=True, text=True, timeout=60)
    return r, r.stdout + r.stderr


def secret_key(tmp_path):
    p = tmp_path / "private" / "aws-creds.ini"
    if not p.exists():
        return None
    m = re.search(r"aws_access_key_id = (\S+)", p.read_text())
    return m and m.group(1)


def calls(tmp_path):
    p = tmp_path / "calls.log"
    return p.read_text() if p.exists() else ""


pytestmark = [needs_task, needs_tools]


# ------------------------------------------------- 1. profile "default"

def test_default_profile_present_and_instance_role_on_other_account(tmp_path):
    b = harness(tmp_path, "default")
    r, out = run(tmp_path, b, "under-test-refresh", profiles=f"default:{WANT}", imds=OTHER)
    assert r.returncode == 0, out
    assert secret_key(tmp_path) == f"AKI-{WANT}-default"
    assert "using the configured AWS profile default instead" in out


def test_default_profile_instance_role_on_intended_account_is_kept(tmp_path):
    """Workshop IDE: instance role on aws.accountId -> same source as before."""
    b = harness(tmp_path, "default")
    r, out = run(tmp_path, b, "under-test-refresh", profiles=f"default:{WANT}", imds=WANT)
    assert r.returncode == 0, out
    assert secret_key(tmp_path) == f"AKI-{WANT}-imds"
    assert "export-credentials" not in calls(tmp_path)


def test_default_profile_not_configured_and_instance_role_on_other_account_fails(tmp_path):
    b = harness(tmp_path, "default")
    r, out = run(tmp_path, b, "under-test-refresh", profiles="", imds=OTHER)
    assert r.returncode != 0
    assert f"resolves to account {OTHER}, not aws.accountId {WANT}" in out
    assert secret_key(tmp_path) is None


def test_default_profile_off_ec2_on_other_account_fails(tmp_path):
    b = harness(tmp_path, "default")
    r, out = run(tmp_path, b, "under-test-refresh", profiles=f"default:{OTHER}", imds=None)
    assert r.returncode != 0
    assert "AWS profile default resolves to account" in out
    assert secret_key(tmp_path) is None


def test_default_profile_off_ec2_on_intended_account(tmp_path):
    b = harness(tmp_path, "default")
    r, out = run(tmp_path, b, "under-test-refresh", profiles=f"default:{WANT}", imds=None)
    assert r.returncode == 0, out
    assert secret_key(tmp_path) == f"AKI-{WANT}-default"


# ------------------------------------------------- 2. named profile

def test_named_profile_is_used_even_on_ec2(tmp_path):
    b = harness(tmp_path, "dev")
    r, out = run(tmp_path, b, "under-test-refresh", profiles=f"default:{OTHER} dev:{WANT}", imds=OTHER)
    assert r.returncode == 0, out
    assert secret_key(tmp_path) == f"AKI-{WANT}-dev"
    assert "api/token" not in calls(tmp_path)


def test_named_profile_on_other_account_fails(tmp_path):
    b = harness(tmp_path, "dev")
    r, out = run(tmp_path, b, "under-test-refresh", profiles=f"dev:{OTHER}")
    assert r.returncode != 0
    assert "AWS profile dev resolves to account" in out
    assert secret_key(tmp_path) is None


def test_named_profile_missing_fails_clearly(tmp_path):
    b = harness(tmp_path, "dev")
    r, out = run(tmp_path, b, "under-test-refresh", profiles="")
    assert r.returncode != 0
    assert "cannot resolve AWS credentials for profile dev" in out


# ------------------------------------------------- 3. no profile

@pytest.mark.parametrize("profile", [None, ""])
def test_no_profile_uses_instance_role_on_intended_account(tmp_path, profile):
    b = harness(tmp_path, profile)
    r, out = run(tmp_path, b, "under-test-refresh", profiles=f"default:{WANT}", imds=WANT)
    assert r.returncode == 0, out
    assert secret_key(tmp_path) == f"AKI-{WANT}-imds"


def test_no_profile_never_falls_back_and_refuses_other_account(tmp_path):
    """No profile = IMDS chosen on purpose: no silent switch to another source."""
    b = harness(tmp_path, None)
    r, out = run(tmp_path, b, "under-test-refresh", profiles=f"default:{WANT}", imds=OTHER)
    assert r.returncode != 0
    assert "EC2 instance role (IMDS) resolves to account" in out
    assert "export-credentials" not in calls(tmp_path)
    assert secret_key(tmp_path) is None


def test_placeholder_account_id_skips_check(tmp_path):
    b = harness(tmp_path, None)
    tf = tmp_path / "Taskfile.yml"
    tf.write_text(tf.read_text().replace(f"AWS_ACCOUNT_ID: '{WANT}'", "AWS_ACCOUNT_ID: <12-digit-account-id>"))
    r, out = run(tmp_path, b, "under-test-refresh", imds=OTHER)
    assert r.returncode == 0, out
    assert "account check skipped" in out


# ------------------------------------------------- 4. check-and-refresh

def secret_b64(aki):
    ini = f"[default]\naws_access_key_id = {aki}\naws_secret_access_key = SAK\naws_session_token = ST\n"
    return base64.b64encode(ini.encode()).decode()


def test_check_refreshes_valid_secret_of_other_account_and_propagates_failure(tmp_path):
    b = harness(tmp_path, "default")
    r, out = run(tmp_path, b, "under-test-check", FAKE_SECRET_B64=secret_b64(f"AKI-{OTHER}-imds"),
                 FAKE_REFRESH_RC="1")
    assert "not for aws.accountId" in out and "REFRESH-CALLED" in out
    assert r.returncode != 0


def test_check_keeps_valid_secret_of_intended_account(tmp_path):
    b = harness(tmp_path, "default")
    r, out = run(tmp_path, b, "under-test-check", FAKE_SECRET_B64=secret_b64(f"AKI-{WANT}-imds"))
    assert r.returncode == 0, out
    assert "ACK credentials valid" in out and "REFRESH-CALLED" not in out


def test_check_expired_keeps_best_effort(tmp_path):
    b = harness(tmp_path, "default")
    r, out = run(tmp_path, b, "under-test-check", FAKE_SECRET_B64=secret_b64("AKI-EXPIRED"),
                 FAKE_REFRESH_RC="1")
    assert "REFRESH-CALLED" in out
    assert r.returncode == 0, out


# ------------------------------------------------- 5. AWS_PROFILE export

def test_env_and_vars_match_kind_crossplane():
    kro, xp = tasks(KRO), tasks(XP)
    for key in ("AWS_PROFILE", "AWS_CONFIG_FILE"):
        assert kro["env"][key] == xp["env"][key], key
        assert kro["vars"][key]["sh"] == xp["vars"][key]["sh"], key


@pytest.mark.parametrize("profile", ["default", "named-p", ""])
def test_rendered_env_matches_kind_crossplane(tmp_path, profile):
    """Through the real root Taskfile: a kind-kro-ack task sees the same AWS_PROFILE and
    AWS_CONFIG_FILE as a kind-crossplane task (it already did via go-task's env leak)."""
    shutil.copy(os.path.join(REPO, "Taskfile.yaml"), tmp_path / "Taskfile.yaml")
    shutil.copytree(os.path.join(REPO, "cluster-providers"), tmp_path / "cluster-providers")
    reg = tmp_path / "gitops" / "addons" / "registry"
    reg.mkdir(parents=True)
    shutil.copy(os.path.join(REPO, "gitops", "addons", "registry", "core.yaml"), reg / "core.yaml")
    (tmp_path / "config.local.yaml").write_text(
        'clusterProvider: "kind-kro-ack"\naws:\n  region: "us-west-2"\n'
        f'  accountId: "{WANT}"\n  profile: "{profile}"\nhub:\n  clusterName: "h"\n')
    probe = '  zz-probe:\n    cmds:\n      - echo "PROBE AWS_PROFILE=$AWS_PROFILE AWS_CONFIG_FILE=$AWS_CONFIG_FILE"\n'
    seen = {}
    for p in ("kind-kro-ack", "kind-crossplane"):
        with open(tmp_path / "cluster-providers" / p / "Taskfile.yaml", "a") as f:
            f.write(probe)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(AWS_CONFIG_FILE=str(tmp_path / "user-config"), AWS_EC2_METADATA_DISABLED="true")
    for p in ("kind-kro-ack", "kind-crossplane"):
        r = subprocess.run([TASK, "-d", str(tmp_path), f"{p}:zz-probe"], env=env,
                           capture_output=True, text=True, timeout=120)
        line = [x for x in r.stdout.splitlines() if x.startswith("PROBE")]
        assert line, r.stdout + r.stderr
        seen[p] = line[0]
    assert seen["kind-kro-ack"] == seen["kind-crossplane"]
    assert f"AWS_PROFILE={profile or 'default'} " in seen["kind-kro-ack"]


# ------------------------------------------------- 6. shellcheck

@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not on PATH")
@pytest.mark.parametrize("task,index", [("credentials:refresh", 1), ("credentials:check-and-refresh", 0)])
def test_shellcheck(tmp_path, task, index):
    text = re.sub(r"\{\{\.[A-Z_]+\}\}", "X", block(task, index))
    f = tmp_path / "block.sh"
    f.write_text("#!/bin/sh\n" + text)
    r = subprocess.run(["shellcheck", "-s", "sh", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
