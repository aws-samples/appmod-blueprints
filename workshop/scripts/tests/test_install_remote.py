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
    for later in ("hub:wait-for-gitlab-init", "task: post-install", "ray:setup", "task: wait-for-spokes", "task: setup-env"):
        assert wait < _index(IDE, later), later
    assert gitlab_bg < wait  # GitLab init must run while the build waits for its PAT


def test_ide_ray_steps_are_non_fatal_known_gap():
    ray = [c for c in WS["install:ide"]["cmds"] if isinstance(c, dict) and "ray:" in c.get("cmd", "")]
    assert len(ray) == 2 and all(c.get("ignore_error") for c in ray)


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
      *install-state*) [ -n "${FAKE_STATE:-}" ] && echo "$FAKE_STATE" || exit 254 ;;
      *install-build-id*) [ -n "${FAKE_BUILD:-}" ] && echo "b-1" || exit 254 ;;
    esac; exit 0 ;;
  "codebuild batch-get-builds") echo "${FAKE_BUILD:-}"; exit 0 ;;
  "secretsmanager get-secret-value") [ -n "${FAKE_CFG:-}" ] && cat "$FAKE_CFG" || exit 254; exit 0 ;;
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

def _kind_args(tmp_path, cfg_text):
    (tmp_path / "bin").mkdir(exist_ok=True)
    kind = tmp_path / "bin" / "kind"
    kind.write_text('#!/bin/sh\necho "$@" > "$KIND_ARGS"\n')
    kind.chmod(0o755)
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(cfg_text)
    cmd = [c for c in KRO["kind:create"]["cmds"] if isinstance(c, str) and "kind create" in c][0]
    cmd = (cmd.replace("{{.CONFIG_FILE}}", str(cfg)).replace("{{.KIND_CLUSTER_NAME}}", "c1")
           .replace("{{.KUBECONFIG}}", "/tmp/k"))
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", KIND_ARGS=str(tmp_path / "args"))
    r = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return (tmp_path / "args").read_text().strip()


@needs_tools
def test_kind_create_default_has_no_image_flag(tmp_path):
    assert _kind_args(tmp_path, "aws:\n  region: x\n") == "create cluster --name c1 --config kind.yaml --kubeconfig /tmp/k"


@needs_tools
def test_kind_create_uses_the_configured_node_image(tmp_path):
    out = _kind_args(tmp_path, "kind:\n  nodeImage: mirror.example/kindest/node:v1.35.0\n")
    assert out.endswith("--image mirror.example/kindest/node:v1.35.0")
