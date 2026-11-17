"""Hermetic tests for the remote install (v0.5 option A): the install runs in CodeBuild
(`task workshop:install:remote`) and the IDE follows (`task workshop:install:ide`).

The default `task install` is untouched; these tests pin the new tasks and scripts:

* DAG order of install:remote, and that nothing in it can fail silently (no ignore_error);
* install:ide holds no platform install, no IAM write and no pivot;
* the platform's remote GitLab wait (gitlabInit: remote) needs a real glpat- token;
* scripts/install-state.sh, scripts/install-remote-wait.sh, workshop/fetch-install-config.sh
  against a fake `aws`.

No AWS, no network, no cluster.

Run:  python -m pytest workshop/scripts/tests/test_install_remote.py -q
"""
import json
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WS = yaml.safe_load(open(os.path.join(REPO, "workshop", "Taskfile.yaml")))["tasks"]
KRO = yaml.safe_load(open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")))["tasks"]
needs_tools = pytest.mark.skipif(not (shutil.which("yq") and shutil.which("jq")), reason="yq/jq not on PATH")
TASK = shutil.which("task")


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


# ---------------------------------------------------------------- install:remote DAG

def test_remote_dag_order():
    order = [
        "task: platform:prepare",
        "task install:hub",
        "task: set-overlay-repo",
        "task: argocd-gitlab-webhook",
        "spoke-dev",
        "spoke-prod",
        "task install:complete",
        "join cloudfront:attach",
        "task: wait-for-spokes",
        ":hub:pivot",
    ]
    idx = [_index(REMOTE, n) for n in order]
    assert idx == sorted(idx), dict(zip(order, idx))


def test_remote_sets_a_git_identity_before_the_first_commit(tmp_path):
    # CodeBuild has no git identity: spokes:enable-kro failed with "Author identity unknown".
    i = _index(REMOTE, "git config --global user.email")
    assert i < _index(REMOTE, "task: set-overlay-repo") and i < _index(REMOTE, "spoke-dev")
    block = REMOTE[i]
    home = tmp_path / "h"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), GIT_CONFIG_NOSYSTEM="1")
    env.pop("GIT_CONFIG_GLOBAL", None)
    subprocess.run(["bash", "-c", block], env=env, check=True, timeout=30)
    def get(key):
        return subprocess.run(["git", "config", "--global", key], env=env, capture_output=True, text=True).stdout.strip()

    assert get("user.email") == "platform@workshops.aws"
    assert get("user.name") == "PEEKS platform"
    # an existing identity is kept (name and email)
    subprocess.run(["git", "config", "--global", "user.email", "me@example.com"], env=env, check=True)
    subprocess.run(["git", "config", "--global", "user.name", "Me Myself"], env=env, check=True)
    subprocess.run(["bash", "-c", block], env=env, check=True, timeout=30)
    assert get("user.email") == "me@example.com"
    assert get("user.name") == "Me Myself"
    # a half identity is completed, never overwritten: email without name, name without email
    for k, v, other, want in (("user.email", "only@example.com", "user.name", "PEEKS platform"),
                              ("user.name", "Only Name", "user.email", "platform@workshops.aws")):
        h = tmp_path / ("half-" + k)
        h.mkdir()
        e2 = dict(env, HOME=str(h))
        subprocess.run(["git", "config", "--global", k, v], env=e2, check=True)
        subprocess.run(["bash", "-c", block], env=e2, check=True, timeout=30)
        got = lambda key: subprocess.run(["git", "config", "--global", key], env=e2, capture_output=True, text=True).stdout.strip()
        assert got(k) == v and got(other) == want, (k, got(k), got(other))
    # and a real commit works with the identity the block sets (the spokes:enable-kro failure)
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], env=env, check=True)
    (repo / "f").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "f"], env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], env=env, check=True)


def test_remote_has_no_silent_failure_and_a_fatal_pivot():
    # `install` runs the pivot with ignore_error (non-fatal); once the build ends, kind is gone,
    # so here a failed pivot must fail the build, and no step may swallow its own failure.
    for c in WS["install:remote"]["cmds"]:
        if isinstance(c, dict):
            assert not c.get("ignore_error"), c
    pivot = [ln for ln in REMOTE if ":hub:pivot" in ln]
    assert len(pivot) == 1 and "PIVOT_DRY_RUN=false" in pivot[0] and "PIVOT_CONFIRM=yes" in pivot[0]


def test_remote_records_a_state_before_each_long_step():
    for step in ("platform:install:hub", "set-overlay-repo", "spokes:enable-kro", "platform:install:complete",
                 "wait-for-spokes", "hub:pivot"):
        assert any("install-state" in ln.replace("{{.STATE}}", "install-state") and f"step={step}" in ln for ln in REMOTE), step


def test_remote_preconditions_guard_the_config():
    pre = " ".join(p["sh"] for p in WS["install:remote"]["preconditions"])
    assert "kind-kro-ack" in pre and "gitlabInit" in pre and "privilegedSteps" in pre


def test_default_install_does_not_know_the_remote_mode():
    text = json.dumps(WS["install"])
    assert "gitlabInit" not in text and "install-state" not in text and "install-remote-wait" not in text


# ---------------------------------------------------------------- install:ide

IAM_WRITE = re.compile(r"aws iam (create|put|attach|update|delete|tag)", re.I)


def test_ide_half_has_no_platform_install_no_iam_write_no_pivot():
    text = "\n".join(IDE)
    for forbidden in ("install:hub", "install:complete", "hub:pivot", "hub:create-mgmt-roles",
                      "spokes:enable", "set-overlay-repo", "cloudfront:attach", "create-capabilities"):
        assert forbidden not in text, forbidden
    assert not IAM_WRITE.search(text)


def test_ide_waits_for_the_build_before_anything_that_needs_the_hub():
    wait = _index(IDE, "install-remote-wait.sh")
    gitlab_bg = _index(IDE, "task -x gitlab:init-ec2")
    for later in ("hub:wait-for-gitlab-init", "task: wait-for-spokes", "task: setup-env"):
        assert wait < _index(IDE, later), later
    assert gitlab_bg < wait  # GitLab init must run while the build waits for its PAT


def test_ide_half_has_no_ray_and_no_kargo_iam_setup():
    # ray:setup / ray:prestage-models / the Kargo controller identity create IAM roles and Pod
    # Identity associations: they run in the build (install:remote-extras), never on the IDE.
    text = "\n".join(IDE)
    assert "ray:" not in text and "kargo" not in text.lower()


EXTRAS = _flat(WS["install:remote-extras"]["cmds"])


def test_remote_extras_order_and_content():
    order = ["task: kargo-identity", ":ray:setup", ":ray:prestage-models", ":ray:wait-image"]
    idx = [_index(EXTRAS, n) for n in order]
    assert idx == sorted(idx), dict(zip(order, idx))
    # the build wraps this task as non-fatal (own status); inside it nothing may swallow a failure
    for c in WS["install:remote-extras"]["cmds"]:
        if isinstance(c, dict):
            assert not c.get("ignore_error"), c
    pre = " ".join(p["sh"] for p in WS["install:remote-extras"]["preconditions"])
    assert "gitlabInit" in pre and "remote" in pre


def test_default_install_does_not_know_the_extras():
    assert "remote-extras" not in json.dumps(WS["install"]) and "kargo-identity" not in json.dumps(WS["install"])


# ---------------------------------------------------------------- kargo-identity

KARGO_SH = open(os.path.join(REPO, "applications", "java", "kargo", "deploy-kargo.sh")).read()


def _kargo_block():
    return "\n".join(c if isinstance(c, str) else c.get("cmd", "") for c in WS["kargo-identity"]["cmds"])


def test_kargo_identity_names_match_deploy_kargo_script():
    # deploy-kargo.sh (module 30.4, run by the participant) looks the role/association up by these
    # names and skips the IAM write when they exist; any drift would send it back to iam:CreateRole.
    block = _kargo_block()
    assert 'HUB_CLUSTER="${RESOURCE_PREFIX:-peeks}-hub"' in KARGO_SH
    assert 'KARGO_ROLE="${HUB_CLUSTER}-kargo-controller-role"' in KARGO_SH
    assert 'HUB_CLUSTER="{{.RESOURCE_PREFIX}}-hub"' in block
    assert 'KARGO_ROLE="${HUB_CLUSTER}-kargo-controller-role"' in block
    for frag in ("--namespace kargo", "--service-account kargo-controller", "pods.eks.amazonaws.com",
                 "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"):
        assert frag in block and frag in KARGO_SH, frag


KARGO_FAKE_AWS = r"""#!/bin/sh
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "iam get-role") if [ "$FAKE_ROLE" = 1 ] || grep -q "iam create-role" "$FAKE_LOG"; then
      case "$*" in *query*) echo arn:aws:iam::000000000000:role/x;; esac; exit 0; else exit 254; fi ;;
  "eks list-pod-identity-associations") [ "$FAKE_PIA" = 1 ] && echo a-123; exit 0 ;;
esac
exit 0
"""


@pytest.mark.parametrize("role,pia,creates", [("0", "0", ["iam create-role", "iam attach-role-policy", "eks create-pod-identity-association"]),
                                               ("1", "0", ["eks create-pod-identity-association"]),
                                               ("1", "1", [])])
def test_kargo_identity_is_idempotent(tmp_path, role, pia, creates):
    (tmp_path / "bin").mkdir()
    f = tmp_path / "bin" / "aws"
    f.write_text(KARGO_FAKE_AWS)
    f.chmod(0o755)
    block = _kargo_block().replace("{{.RESOURCE_PREFIX}}", "acme").replace("{{.AWS_REGION}}", "us-west-2")
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "c.log"),
               FAKE_ROLE=role, FAKE_PIA=pia)
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + block], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = (tmp_path / "c.log").read_text()
    for w in ("iam create-role", "iam attach-role-policy", "eks create-pod-identity-association"):
        assert (w in calls) == (w in creates), (w, calls)
    assert "acme-hub-kargo-controller-role" in calls and "--cluster-name acme-hub" in calls


def test_ide_refuses_the_builds_own_config():
    pre = " ".join(p["sh"] for p in WS["install:ide"]["preconditions"])
    assert "gitlabInit" in pre and "!= \"remote\"" in pre


# ---------------------------------------------------------------- remote GitLab wait (platform)

def _wait_block():
    c = KRO["hub:wait-for-gitlab-init"]["cmds"][0]
    return c["cmd"] if isinstance(c, dict) else c


def _run_wait(tmp_path, token, mode="remote", max_wait="1"):
    (tmp_path / "bin").mkdir(exist_ok=True)
    fake = tmp_path / "bin" / "aws"
    fake.write_text('#!/bin/sh\necho "aws $*" >> "$FAKE_LOG"\n'
                    '[ -n "$FAKE_SECRET" ] && echo "$FAKE_SECRET" || exit 254\n')
    fake.chmod(0o755)
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(f'hub:\n  clusterName: acme-hub\ngitlabInit: {mode}\n' if mode else "hub:\n  clusterName: acme-hub\n")
    block = (_wait_block().replace("{{.CONFIG_FILE}}", str(cfg)).replace("{{.HUB_CLUSTER_NAME}}", "acme-hub")
             .replace("{{.AWS_REGION}}", "us-west-2"))
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "calls.log"),
               FAKE_SECRET=json.dumps({"git_token": token}) if token is not None else "",
               GITLAB_REMOTE_WAIT=max_wait, GITLAB_REMOTE_POLL="1")
    r = subprocess.run(["bash", "-c", block], env=env, capture_output=True, text=True, timeout=60)
    return r, r.stdout + r.stderr


GOOD_PAT = "glpat-abcDEF0123456789_-xyz"


@needs_tools
def test_remote_wait_passes_on_a_real_pat_and_snapshots_it_into_the_config(tmp_path):
    r, out = _run_wait(tmp_path, GOOD_PAT)
    assert r.returncode == 0, out
    assert "GitLab PAT present" in out
    # every GIT_PASSWORD var reads this key first: Secrets Manager is not read again
    assert f"gitlabRootPassword: {GOOD_PAT}" in (tmp_path / "config.local.yaml").read_text()


@needs_tools
def test_remote_wait_accepts_a_routable_gitlab_pat(tmp_path):
    # GitLab routable tokens: glpat-<payload>.<2-char version>.<suffix> (51 chars)
    pat = "glpat-" + "aB3_-" * 7 + "xyz" + ".01." + "abcdefghi"
    r, out = _run_wait(tmp_path, pat)
    assert r.returncode == 0, out
    assert f"gitlabRootPassword: {pat}" in (tmp_path / "config.local.yaml").read_text()


@needs_tools
@pytest.mark.parametrize("token", ["", None, "root-IDEPASSWORD"])
def test_remote_wait_fails_without_a_real_pat(tmp_path, token):
    # a missing secret must not read as "done"; the CDK-seeded placeholder (root-<ide password>)
    # is not a PAT either: it keeps polling and ends in "did not finish", never "unexpected format"
    r, out = _run_wait(tmp_path, token)
    assert r.returncode == 1, out
    assert "did not finish" in out


@needs_tools
@pytest.mark.parametrize("token", [
    "glpat-abc123",                        # too short
    "glpat-abcDEF0123456789_-xyz$(touch PWNED)",
    "glpat-abcDEF0123456789_-xyz'; touch PWNED; '",
    "glpat-abcDEF0123456789_-xyz`touch PWNED`",
    "glpat-abcDEF0123456789_-xyz\nextra",
    "glpat-abcDEF0123456789_-xyz@evil.example",
    # appended to a token that is long enough on its own (pre-review nit of f27e0f1ed)
    "glpat-abcDEF0123456789_-xyz;",
    "glpat-abcDEF0123456789_-xyz;touch PWNED",
    "glpat-abcDEF0123456789_-xyz&&touch PWNED",
    "glpat-abcDEF0123456789_-xyz|touch PWNED",
    "glpat-abcDEF0123456789_-xyz touch PWNED",
    "glpat-abcDEF0123456789_-xyz..",
    "glpat-abcDEF0123456789_-xyz../..",
    "glpat-abcDEF0123456789_-xyz.",
    "glpat-abcDEF0123456789_-xyz.01..abcdefghi",
])
def test_remote_wait_refuses_a_token_that_could_inject_shell(tmp_path, token):
    # the IDE can write <hub>/secrets; go-task pastes the token into shell text later
    r, out = _run_wait(tmp_path, token)
    assert r.returncode == 1, out
    assert "unexpected format" in out
    assert "gitlabRootPassword" not in (tmp_path / "config.local.yaml").read_text()
    assert not (tmp_path / "PWNED").exists() and not os.path.exists("PWNED")


@needs_tools
def test_remote_wait_polls_through_the_cdk_placeholder_until_the_pat_appears(tmp_path):
    # fresh account: <hub>/secrets.git_token is the placeholder first, gitlab:init-ec2 swaps in the PAT
    (tmp_path / "bin").mkdir()
    state = tmp_path / "n"
    fake = tmp_path / "bin" / "aws"
    fake.write_text('#!/bin/sh\nn=$(cat "%s" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "%s"\n'
                    'if [ "$n" -lt 3 ]; then echo \'{"git_token":"root-IDEPASSWORD"}\'; '
                    'else echo \'{"git_token":"%s"}\'; fi\n' % (state, state, GOOD_PAT))
    fake.chmod(0o755)
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text("hub:\n  clusterName: acme-hub\ngitlabInit: remote\n")
    block = (_wait_block().replace("{{.CONFIG_FILE}}", str(cfg)).replace("{{.HUB_CLUSTER_NAME}}", "acme-hub")
             .replace("{{.AWS_REGION}}", "us-west-2"))
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}",
               GITLAB_REMOTE_WAIT="30", GITLAB_REMOTE_POLL="1")
    r = subprocess.run(["bash", "-c", block], env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "unexpected format" not in out
    assert f"gitlabRootPassword: {GOOD_PAT}" in cfg.read_text()


@needs_tools
def test_local_mode_is_untouched_by_the_remote_branch(tmp_path):
    # no gitlabInit key: the old pid-file logic answers (no job found = done), no secret read
    r, out = _run_wait(tmp_path, None, mode=None)
    assert r.returncode == 0, out
    assert "aws " not in (tmp_path / "calls.log").read_text() if (tmp_path / "calls.log").exists() else True


# ---------------------------------------------------------------- scripts

FAKE_AWS = r"""#!/bin/sh
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "ssm put-parameter") [ "${FAKE_PUT_FAIL:-0}" = 1 ] && exit 254
    prev=""; for a in "$@"; do [ "$prev" = "--value" ] && echo "$a" > "$FAKE_PUT_VALUE"; prev="$a"; done; exit 0 ;;
  "ssm get-parameter")
    case "$*" in
      *install-state*)
        # FAKE_STATE_NEXT: the value from the second read on (the build wrote OK meanwhile).
        n=$(cat "$FAKE_LOG.reads" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$FAKE_LOG.reads"
        V="${FAKE_STATE:-}"; [ "$n" -gt 1 ] && [ -n "${FAKE_STATE_NEXT:-}" ] && V="$FAKE_STATE_NEXT"
        [ -n "$V" ] || exit 254
        case "$*" in
          *LastModifiedDate*) printf '%s\t%s\n' "$V" "${FAKE_STATE_AT:-2026-11-15T10:00:00.123000+00:00}" ;;
          *) echo "$V" ;;
        esac ;;
      *install-build-id*) [ -n "${FAKE_BUILD:-}" ] && echo "b-1" || exit 254 ;;
    esac; exit 0 ;;
  "codebuild batch-get-builds")
    case "$*" in
      *endTime*) printf '%s\t%s\t%s\n' "${FAKE_BUILD:-}" "${FAKE_BUILD_START:-2026-11-15T09:00:00.500000+00:00}" "${FAKE_BUILD_END:-None}" ;;
      *startTime*) printf '%s\t%s\n' "${FAKE_BUILD:-}" "${FAKE_BUILD_START:-2026-11-15T09:00:00.500000+00:00}" ;;
      *) echo "${FAKE_BUILD:-}" ;;
    esac; exit 0 ;;
  "secretsmanager get-secret-value") [ -n "${FAKE_CFG:-}" ] && cat "$FAKE_CFG" || exit 254; exit 0 ;;
  "secretsmanager describe-secret") [ -n "${FAKE_CONFIG_AT:-}" ] && echo "$FAKE_CONFIG_AT" || exit 254; exit 0 ;;
esac
exit 0
"""


def _env(tmp_path, **extra):
    (tmp_path / "bin").mkdir(exist_ok=True)
    p = tmp_path / "bin" / "aws"
    p.write_text(FAKE_AWS)
    p.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "calls.log"),
               FAKE_PUT_VALUE=str(tmp_path / "put"), RESOURCE_PREFIX="acme", INSTALL_REMOTE_INTERVAL="1",
               INSTALL_REMOTE_TIMEOUT="2", INSTALL_CONFIG_POLL="1", INSTALL_CONFIG_WAIT="2")
    env.update(extra)
    return env


def _sh(script, env, *args):
    return subprocess.run(["sh", os.path.join(REPO, script), *args], env=env, capture_output=True, text=True, timeout=60)


def test_install_state_writes_a_prefixed_parameter(tmp_path):
    r = _sh("scripts/install-state.sh", _env(tmp_path), "RUNNING step=hub:seed")
    assert r.returncode == 0
    assert "--name /acme/install-state" in (tmp_path / "calls.log").read_text()
    assert (tmp_path / "put").read_text().startswith("RUNNING step=hub:seed 20")


def test_install_state_never_fails_the_install(tmp_path):
    r = _sh("scripts/install-state.sh", _env(tmp_path, FAKE_PUT_FAIL="1"), "RUNNING")
    assert r.returncode == 0 and "could not write" in r.stderr
    r = _sh("scripts/install-state.sh", _env(tmp_path, RESOURCE_PREFIX="", CONFIG_FILE="/nonexistent"), "RUNNING")
    assert r.returncode == 0 and "no resource prefix" in r.stderr


@needs_tools
@pytest.mark.parametrize("state,build,rc", [
    ("OK 2026-11-15T10:00:00Z", "", 0),
    ("FAILED rc=1 step=hub:seed 2026-11-15T10:00:00Z", "", 1),
    ("RUNNING step=hub:claim 2026-11-15T10:00:00Z", "FAILED", 1),     # build died without writing FAILED
    ("RUNNING step=hub:claim 2026-11-15T10:00:00Z", "TIMED_OUT", 1),
    ("RUNNING step=hub:claim 2026-11-15T10:00:00Z", "STOPPED", 1),
    ("RUNNING step=hub:claim 2026-11-15T10:00:00Z", "IN_PROGRESS", 1),  # still running: timeout
    ("", "", 1),                                                         # nothing recorded: timeout
])
def test_install_remote_wait(tmp_path, state, build, rc):
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE=state, FAKE_BUILD=build))
    assert r.returncode == rc, r.stdout + r.stderr
    # the reason must be the right one, not just a timeout
    if state.startswith("FAILED"):
        assert "remote install failed" in r.stderr
    elif build in ("FAILED", "TIMED_OUT", "STOPPED"):
        assert f"ended as {build}" in r.stderr
    elif rc == 1:
        assert "did not finish" in r.stderr


@needs_tools
def test_install_remote_wait_fails_fast_on_a_build_that_succeeded_without_ok(tmp_path):
    # install-state.sh drops a failed write: the build can end SUCCEEDED with no OK recorded.
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE="RUNNING step=oap 2026-11-15T10:00:00Z",
                                                   FAKE_BUILD="SUCCEEDED", INSTALL_REMOTE_TIMEOUT="600"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ended as SUCCEEDED without recording OK" in r.stderr
    assert "did not finish" not in r.stderr  # not a wait until the timeout


@needs_tools
def test_install_remote_wait_rereads_the_state_when_the_build_succeeded(tmp_path):
    # OK was written between the state read and the build-status read.
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE="RUNNING step=oap 2026-11-15T10:00:00Z",
                                                   FAKE_STATE_NEXT="OK 2026-11-15T10:05:00Z", FAKE_BUILD="SUCCEEDED"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "remote install finished: OK" in r.stdout


@needs_tools
@pytest.mark.parametrize("state", ["OK 2026-11-14T10:00:00Z", "FAILED rc=1 step=hub:seed 2026-11-14T10:00:00Z"])
def test_install_remote_wait_ignores_a_state_from_an_earlier_build(tmp_path, state):
    # The state was last written BEFORE the current build started: it is the previous build's.
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE=state, FAKE_BUILD="IN_PROGRESS",
                                                   FAKE_STATE_AT="2026-11-14T10:00:00+00:00",
                                                   FAKE_BUILD_START="2026-11-15T09:00:00+00:00"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ignoring a state of an earlier build" in r.stdout
    assert "did not finish" in r.stderr and "remote install failed" not in r.stderr


@needs_tools
@pytest.mark.parametrize("state_at,build_start,rc", [
    ("1700000100.25", "1700000000.75", 0),   # epoch timestamps (CLI v1 / cli_timestamp_format)
    ("1699999000.0", "1700000000.75", 1),    # stale, epoch form
    ("2026-11-15T09:00:00.900000+00:00", "2026-11-15T09:00:00.100000+00:00", 0),  # same second
])
def test_install_remote_wait_compares_timestamps_in_both_cli_formats(tmp_path, state_at, build_start, rc):
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE="OK now", FAKE_BUILD="IN_PROGRESS",
                                                   FAKE_STATE_AT=state_at, FAKE_BUILD_START=build_start))
    assert r.returncode == rc, r.stdout + r.stderr


@needs_tools
@pytest.mark.parametrize("local_rc,rc,msg", [("1", 1, "failed on this host"), ("0", 1, "did not finish")])
def test_install_remote_wait_stops_on_a_failed_local_step(tmp_path, local_rc, rc, msg):
    f = tmp_path / "gitlab-init.rc"
    f.write_text(local_rc + "\n")
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE="RUNNING step=hub:claim now",
                                                   FAKE_BUILD="IN_PROGRESS", INSTALL_REMOTE_LOCAL_RC=str(f)))
    assert r.returncode == rc and msg in r.stderr, r.stdout + r.stderr


@needs_tools
@pytest.mark.parametrize("state_at,rc", [
    ("2026-11-15T10:00:00+00:00", 1),   # the previous run's OK, its build id still current: ignored
    ("2026-11-15T12:00:01+00:00", 0),   # written after this run started
])
def test_install_remote_wait_ignores_a_state_older_than_this_run(tmp_path, state_at, rc):
    not_before = int(subprocess.check_output(["date", "-d", "2026-11-15T12:00:00+00:00", "+%s"]).strip())
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE="OK 2026-11-15T10:00:00Z", FAKE_BUILD="SUCCEEDED",
                                                   FAKE_STATE_AT=state_at, FAKE_BUILD_START="2026-11-15T09:00:00+00:00",
                                                   INSTALL_REMOTE_NOT_BEFORE=str(not_before)))
    assert r.returncode == rc, r.stdout + r.stderr
    if rc:
        assert "ignoring a state of an earlier build" in r.stdout and "without recording OK" in r.stderr


def _epoch(iso):
    return subprocess.check_output(["date", "-d", iso, "+%s"], text=True).strip()


@needs_tools
@pytest.mark.parametrize("build,state", [("SUCCEEDED", "OK 2026-11-15T10:00:00Z"),
                                         ("FAILED", "FAILED rc=1 step=hub:seed 2026-11-15T10:00:00Z")])
def test_install_remote_wait_ignores_a_build_that_ended_before_this_run(tmp_path, build, state):
    # install-build-id still names the previous build, which ended before this run started.
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE=state, FAKE_BUILD=build,
                                                   FAKE_STATE_AT="2026-11-15T10:00:00+00:00",
                                                   FAKE_BUILD_START="2026-11-15T09:00:00+00:00",
                                                   FAKE_BUILD_END="2026-11-15T10:01:00+00:00",
                                                   INSTALL_REMOTE_NOT_BEFORE=_epoch("2026-11-15T12:00:00+00:00")))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "did not finish" in r.stderr and "Re-run fetch-install-config.sh" in r.stderr  # waited, then the hint
    assert "ended (" in r.stdout and "remote install failed" not in r.stderr and "without recording" not in r.stderr


@needs_tools
def test_install_remote_wait_follows_a_finished_build_with_not_before_zero(tmp_path):
    # re-running install:ide after the build finished: the operator opts in to the earlier build
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE="OK 2026-11-15T10:00:00Z", FAKE_BUILD="SUCCEEDED",
                                                   FAKE_STATE_AT="2026-11-15T10:00:00+00:00",
                                                   FAKE_BUILD_START="2026-11-15T09:00:00+00:00",
                                                   FAKE_BUILD_END="2026-11-15T10:01:00+00:00",
                                                   INSTALL_REMOTE_NOT_BEFORE="0"))
    assert r.returncode == 0, r.stdout + r.stderr


def test_ide_does_not_tie_the_cut_off_to_its_own_start():
    # the cut-off is the publish time of the config this host fetched (the script's default):
    # the build may fail before install:ide starts, and that FAILED must still end the wait
    line = IDE[_index(IDE, "install-remote-wait.sh")]
    assert "INSTALL_START" not in line and "INSTALL_REMOTE_NOT_BEFORE=" not in line


@needs_tools
@pytest.mark.parametrize("case,state,state_at,build,build_end,rc,msg", [
    # the build that published the config failed after the publish, before install:ide started
    ("early-fail", "FAILED rc=2 step=install 2026-11-15T12:10:00Z", "2026-11-15T12:10:00+00:00",
     "FAILED", "2026-11-15T12:11:00+00:00", 1, "remote install failed"),
    # re-running install:ide after its build finished: follows that build
    ("rerun", "OK 2026-11-15T13:00:00Z", "2026-11-15T13:00:00+00:00",
     "SUCCEEDED", "2026-11-15T13:20:00+00:00", 0, "remote install finished"),
    # the previous build's OK, the new build has published its config but not written its id
    ("stale-ok", "OK 2026-11-15T10:00:00Z", "2026-11-15T10:00:00+00:00",
     "SUCCEEDED", "2026-11-15T10:01:00+00:00", 1, "did not finish"),
])
def test_install_remote_wait_cut_off_is_the_config_publish_time(tmp_path, case, state, state_at, build, build_end, rc, msg):
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE=state, FAKE_BUILD=build, FAKE_STATE_AT=state_at,
                                                   FAKE_BUILD_START="2026-11-15T09:00:00+00:00" if case == "stale-ok"
                                                   else "2026-11-15T11:58:00+00:00",
                                                   FAKE_BUILD_END=build_end, FAKE_CONFIG_AT="2026-11-15T12:00:00+00:00"))
    assert r.returncode == rc, r.stdout + r.stderr
    assert msg in r.stdout + r.stderr
    if case == "early-fail":
        assert "did not finish" not in r.stderr  # at once, not after the timeout


@needs_tools
def test_install_remote_wait_prints_its_cut_off(tmp_path):
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_CONFIG_AT="2026-11-15T12:00:00+00:00"), "--print-not-before")
    assert (r.returncode, r.stdout.strip()) == (0, _epoch("2026-11-15T12:00:00+00:00"))
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path), "--print-not-before")  # secret unreadable: no cut-off
    assert (r.returncode, r.stdout.strip()) == (0, "")
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_CONFIG_AT="2026-11-15T12:00:00+00:00",
                                                   INSTALL_REMOTE_NOT_BEFORE="5"), "--print-not-before")
    assert r.stdout.strip() == "5"  # operator override


def test_install_remote_wait_refuses_a_bad_not_before(tmp_path):
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE="OK now", INSTALL_REMOTE_NOT_BEFORE="yesterday"))
    assert r.returncode == 1 and "must be epoch seconds" in r.stderr



def test_ide_passes_the_gitlab_init_rc_to_the_wait():
    line = IDE[_index(IDE, "install-remote-wait.sh")]
    assert "INSTALL_REMOTE_LOCAL_RC=/tmp/gitlab-init.rc" in line


def test_wait_documents_no_unused_variable():
    text = open(os.path.join(REPO, "scripts", "install-remote-wait.sh")).read()
    for var in re.findall(r"^#\s+(INSTALL_REMOTE_[A-Z_]+)", text, re.M):
        assert text.count(var) > 1, var  # documented AND read


def test_install_remote_wait_is_read_only(tmp_path):
    _sh("scripts/install-remote-wait.sh", _env(tmp_path, FAKE_STATE="OK now"))
    calls = (tmp_path / "calls.log").read_text()
    assert "put-parameter" not in calls and "start-build" not in calls


CFG = """clusterProvider: kind-kro-ack
resourcePrefix: acme
aws: {region: us-west-2, accountId: "111122223333", profile: install, ideRoleArn: "arn:aws:iam::111122223333:role/ide"}
gitlabInit: remote
hub: {clusterName: acme-hub}
"""


@needs_tools
def test_fetch_install_config_strips_build_only_keys_and_sets_external(tmp_path):
    src = tmp_path / "published.yaml"
    src.write_text(CFG)
    out = tmp_path / "config.local.yaml"
    r = subprocess.run(["bash", os.path.join(REPO, "workshop", "fetch-install-config.sh")],
                       env=_env(tmp_path, FAKE_CFG=str(src), OUTPUT_FILE=str(out)), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    got = yaml.safe_load(out.read_text())
    assert "gitlabInit" not in got and "ideRoleArn" not in got["aws"]
    assert got["aws"]["profile"] == "default"              # not the build's named profile
    assert got["privilegedSteps"] == "external"            # destroy on the IDE is Kubernetes-only
    assert got["hub"]["clusterName"] == "acme-hub"
    assert oct(out.stat().st_mode & 0o777) == "0o600"


@needs_tools
def test_fetch_install_config_fails_when_the_build_never_published(tmp_path):
    r = subprocess.run(["bash", os.path.join(REPO, "workshop", "fetch-install-config.sh")],
                       env=_env(tmp_path, OUTPUT_FILE=str(tmp_path / "c.yaml")), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and not (tmp_path / "c.yaml").exists()


# ---------------------------------------------------------------- AWS_CONFIG_FILE probe (CodeBuild)

KRO_VARS = yaml.safe_load(open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")))["vars"]


def _config_file_for(tmp_path, container_env):
    (tmp_path / "bin").mkdir(exist_ok=True)
    curl = tmp_path / "bin" / "curl"
    curl.write_text("#!/bin/sh\necho 401\nexit 0\n")  # answers like any HTTP server, even refusing
    curl.chmod(0o755)
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text('aws:\n  installRoleArn: "arn:aws:iam::111111111111:role/x"\n')
    block = KRO_VARS["AWS_CONFIG_FILE"]["sh"].replace("{{.ROOT_DIR}}", str(tmp_path)).replace("{{.CONFIG_FILE}}", str(cfg))
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", HOME=str(tmp_path), **container_env)
    r = subprocess.run(["bash", "-c", block], env=env, capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


@needs_tools
def test_codebuild_container_credentials_skip_the_instance_metadata_probe(tmp_path):
    out = _config_file_for(tmp_path, {"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/x"})
    assert out == str(tmp_path / ".aws" / "config")
    assert not (tmp_path / "private" / "aws-config").exists()


@needs_tools
def test_ec2_still_gets_the_generated_config(tmp_path):
    out = _config_file_for(tmp_path, {})
    assert out == str(tmp_path / "private" / "aws-config")


# ---------------------------------------------------------------- kind node image (Docker Hub rate limit)

def _kind_args(tmp_path, cfg_text, cgroup_fs="cgroup2fs"):
    (tmp_path / "bin").mkdir(exist_ok=True)
    kind = tmp_path / "bin" / "kind"
    kind.write_text('#!/bin/sh\necho "$@" > "$KIND_ARGS"\n')
    kind.chmod(0o755)
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(cfg_text)
    cmd = [c for c in KRO["kind:create"]["cmds"] if isinstance(c, str) and "kind create" in c][0]
    cmd = (cmd.replace("{{.CONFIG_FILE}}", str(cfg)).replace("{{.KIND_CLUSTER_NAME}}", "c1")
           .replace("{{.KUBECONFIG}}", "/tmp/k"))
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", KIND_ARGS=str(tmp_path / "args"),
               KIND_CGROUP_FS=cgroup_fs)
    r = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=30,
                       cwd=os.path.join(REPO, "cluster-providers", "kind-kro-ack"))
    assert r.returncode == 0, r.stderr
    return (tmp_path / "args").read_text().strip()


@needs_tools
def test_kind_create_default_has_no_image_flag(tmp_path):
    assert _kind_args(tmp_path, "aws:\n  region: x\n") == "create cluster --name c1 --config kind.yaml --kubeconfig /tmp/k"


@needs_tools
def test_kind_create_uses_the_configured_node_image(tmp_path):
    out = _kind_args(tmp_path, "kind:\n  nodeImage: mirror.example/kindest/node:v1.35.0\n")
    assert out.endswith("--image mirror.example/kindest/node:v1.35.0")


@needs_tools
def test_kind_create_on_cgroup_v1_host_disables_fail_cgroup_v1(tmp_path):
    # kubelet >= 1.35 exits on cgroup v1 (CodeBuild host) unless failCgroupV1 is false.
    out = _kind_args(tmp_path, "aws:\n  region: x\n", cgroup_fs="tmpfs")
    cfg = re.search(r"--config (\S+)", out).group(1)
    assert cfg != "kind.yaml"
    doc = yaml.safe_load(open(cfg))
    patches = [yaml.safe_load(x) for x in doc["kubeadmConfigPatches"]]
    assert {"kind": "KubeletConfiguration", "failCgroupV1": False} in patches
    assert doc["nodes"] == [{"role": "control-plane"}]


# ---------------------------------------------------------------- ray:wait-image strict mode

RAY = yaml.safe_load(open(os.path.join(REPO, "cluster-providers", "common", "Taskfile.ray.yaml")))["tasks"]


def _wait_image_block():
    c = RAY["wait-image"]["cmds"][0]
    b = c["cmd"] if isinstance(c, dict) else c
    return (b.replace("{{.RAY_ECR_REPO}}", "acme-ray-vllm-custom").replace("{{.AWS_REGION}}", "us-west-2"))


def _run_wait_image(tmp_path, strict, ecr_ok):
    (tmp_path / "bin").mkdir(exist_ok=True)
    f = tmp_path / "bin" / "aws"
    f.write_text("#!/bin/sh\n" + ("exit 0\n" if ecr_ok else "exit 254\n"))
    f.chmod(0o755)
    (tmp_path / "bin" / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "bin" / "sleep").chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    if strict:
        env["RAY_WAIT_STRICT"] = "1"
    return subprocess.run(["bash", "-c", _wait_image_block()], env=env, capture_output=True, text=True, timeout=30)


def test_wait_image_is_lenient_by_default_and_strict_on_request(tmp_path):
    # default (task install on the IDE): a slow build must not fail the install
    assert _run_wait_image(tmp_path, False, False).returncode == 0
    # install:remote-extras: a missing image after the timeout is a visible failure
    r = _run_wait_image(tmp_path, True, False)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "vLLM image" in r.stdout
    # strict mode still succeeds when the image is there
    assert _run_wait_image(tmp_path, True, True).returncode == 0


def test_remote_extras_asks_for_strict_wait_image():
    line = [ln for ln in EXTRAS if ":ray:wait-image" in ln][0]
    assert "RAY_WAIT_STRICT" in line


# ---------------------------------------------------------------- install:ide final report

IDE_REPORT = [c for c in IDE if "idc-status" in c and "extras-status" in c][0]


@pytest.mark.parametrize("idc,extras,ok", [
    ("SUCCESS 2026-11-16T00:00:00Z", "OK 2026-11-16T00:00:00Z", True),
    ("SKIPPED 2026-11-16T00:00:00Z", "RUNNING 2026-11-16T00:00:00Z", True),  # the image build goes on
    ("FAILED rc=1 2026-11-16T00:00:00Z", "OK 2026-11-16T00:00:00Z", False),
    ("SUCCESS 2026-11-16T00:00:00Z", "FAILED: install:remote-extras, see the CodeBuild log", False),
    ("", "", False),                                                          # unreadable
    ("SUCCESS 2026-11-15T00:00:00Z", "OK 2026-11-16T13:00:00Z", False),      # idc-status of an earlier run
    ("SUCCESS 2026-11-16T13:00:00Z", "RUNNING 2026-11-15T00:00:00Z", False),  # extras of an earlier run
])
def test_ide_reports_both_build_statuses(tmp_path, idc, extras, ok):
    (tmp_path / "bin").mkdir()
    fake = tmp_path / "bin" / "aws"
    fake.write_text('#!/bin/sh\ncase "$*" in\n  *idc-status*) [ -n "$IDC" ] && echo "$IDC" || exit 254 ;;\n'
                    '  *extras-status*) [ -n "$EXTRAS" ] && echo "$EXTRAS" || exit 254 ;;\n'
                    '  *describe-secret*) echo 2026-11-15T12:00:00+00:00 ;;\nesac\n')
    fake.chmod(0o755)
    block = re.sub(r"\{\{\.C_[A-Z]+\}\}", "", IDE_REPORT).replace("{{.RESOURCE_PREFIX}}", "acme") \
        .replace("{{.AWS_REGION}}", "us-west-2").replace("{{.INSTALL_START}}", "0").replace("{{.REPO}}", REPO)
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", IDC=idc, EXTRAS=extras, RESOURCE_PREFIX="acme")
    env.pop("INSTALL_REMOTE_NOT_BEFORE", None)
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + block], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr  # never fatal
    assert f"(idc-status): " in r.stdout and (idc or "unknown") in r.stdout and (extras or "unknown") in r.stdout
    assert ("from an earlier run" in r.stdout) is ("2026-11-15" in idc + extras), r.stdout
    assert ("IDE install complete" in r.stdout) is ok, r.stdout
    assert ("did not succeed" in r.stdout) is (not ok), r.stdout



@needs_tools
def test_install_remote_wait_falls_back_to_the_config_file_time_when_the_secret_is_unreadable(tmp_path):
    # describe-secret fails (ExpiredToken): the cut-off must not silently disappear
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text("resourcePrefix: acme\n")
    stamp = int(_epoch("2026-11-15T12:00:00+00:00"))
    os.utime(cfg, (stamp, stamp))
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, CONFIG_FILE=str(cfg)), "--print-not-before")
    assert (r.returncode, r.stdout.strip()) == (0, str(stamp))
    assert "could not read when acme/install-config was published" in r.stderr
    # and an earlier build's OK is then still ignored
    r = _sh("scripts/install-remote-wait.sh", _env(tmp_path, CONFIG_FILE=str(cfg), FAKE_STATE="OK 2026-11-15T10:00:00Z",
                                                   FAKE_BUILD="IN_PROGRESS", FAKE_STATE_AT="2026-11-15T10:00:00+00:00"))
    assert r.returncode == 1 and "ignoring a state of an earlier build" in r.stdout



FAKE_AWS_FETCH = r"""#!/bin/sh
case "$1 $2" in
  "secretsmanager get-secret-value") cat "$FAKE_CFG" ;;
  "secretsmanager describe-secret") echo "$FAKE_PUB" ;;
  "codebuild list-builds-for-project") [ "${FAKE_LIST_FAIL:-0}" = 1 ] && exit 254; echo "${FAKE_NEWEST:-None}" ;;
  "codebuild batch-get-builds") echo "$FAKE_NEWEST_START" ;;
esac
exit 0
"""


@needs_tools
@pytest.mark.parametrize("pub,newest,start,list_fail,rc,msg", [
    # the published config is the previous build's: wait for the new one (here: timeout)
    ("2026-11-15T10:00:00+00:00", "acme-install:2", "2026-11-15T12:00:00+00:00", False, 1, "from an earlier build"),
    # published after the newest build started: taken
    ("2026-11-15T12:05:00+00:00", "acme-install:2", "2026-11-15T12:00:00+00:00", False, 0, "wrote"),
    # no build at all yet: taken (residual stated in install-remote-wait.sh)
    ("2026-11-15T10:00:00+00:00", "None", "", False, 0, "wrote"),
    # cannot list the builds: taken, with a warning
    ("2026-11-15T10:00:00+00:00", "", "", True, 0, "could not list"),
])
def test_fetch_install_config_skips_an_earlier_builds_config(tmp_path, pub, newest, start, list_fail, rc, msg):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "aws").write_text(FAKE_AWS_FETCH)
    (tmp_path / "bin" / "aws").chmod(0o755)
    src = tmp_path / "published.yaml"
    src.write_text(CFG)
    out = tmp_path / "c.yaml"
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", RESOURCE_PREFIX="acme", OUTPUT_FILE=str(out),
               FAKE_CFG=str(src), FAKE_PUB=pub, FAKE_NEWEST=newest, FAKE_NEWEST_START=start,
               FAKE_LIST_FAIL="1" if list_fail else "0", INSTALL_CONFIG_POLL="1", INSTALL_CONFIG_WAIT="2")
    r = subprocess.run(["bash", os.path.join(REPO, "workshop", "fetch-install-config.sh")], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == rc, r.stdout + r.stderr
    assert msg in r.stdout + r.stderr
    assert out.exists() is (rc == 0)
