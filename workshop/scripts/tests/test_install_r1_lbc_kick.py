"""Hermetic tests for install perf R1: unstick the aws-load-balancer-controller app while the
platform ALB is late.

Covers:
  * scripts/argocd-app-kick.sh: when it patches, and what it patches (a plain `.operation`
    patch is ignored by Argo CD while an operation sits in retry backoff, so the helper must
    also clear status.operationState in that case, and must never interrupt a running attempt);
  * scripts/cloudfront-attach-origin.sh: the ALB wait loop kicks the LBC app from 2 min on,
    at most 3 times, and never when the app is Healthy;
  * hub:settle (kind-kro-ack): the same once-capped LBC remediation.

Everything runs with bash against fake `kubectl`/`aws` and a no-op `sleep`. No cluster.

Run:  python -m pytest workshop/scripts/tests/test_install_r1_lbc_kick.py -q
"""
import json
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash") or not shutil.which("jq"):
    pytest.skip("bash and jq required", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
KICK = os.path.join(REPO, "scripts", "argocd-app-kick.sh")
ATTACH = os.path.join(REPO, "scripts", "cloudfront-attach-origin.sh")
PROVIDER_TF = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")

BACKOFF = {
    "spec": {"syncPolicy": {"syncOptions": ["CreateNamespace=true"],
                            "retry": {"limit": -1, "backoff": {"duration": "5s", "factor": 2, "maxDuration": "10m"}}}},
    "status": {"health": {"status": "Progressing"},
               "operationState": {"phase": "Running", "finishedAt": "2026-01-01T00:00:00Z"}},
}
RUNNING = {"spec": {}, "status": {"health": {"status": "Progressing"},
                                  "operationState": {"phase": "Running"}}}
HEALTHY = {"spec": {}, "status": {"health": {"status": "Healthy"},
                                  "operationState": {"phase": "Succeeded", "finishedAt": "x"}}}
FAILED = {"spec": {}, "status": {"health": {"status": "Degraded"},
                                 "operationState": {"phase": "Failed", "finishedAt": "x"}}}


def _fake_bin(tmp_path, app_json):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    (tmp_path / "app.json").write_text(json.dumps(app_json))
    (b / "kubectl").write_text(
        '#!/usr/bin/env bash\n'
        'echo "$*" >> "$T/kubectl.calls"\n'
        'case "$*" in\n'
        '  *"get applications.argoproj.io"*"-o json"*) cat "$T/app.json";;\n'
        '  *"get applications.argoproj.io"*) cat "$T/apps.table" 2>/dev/null;;\n'
        '  *"patch applications.argoproj.io"*) shift $(( $# - 1 )); echo "$1" >> "$T/patches";;\n'
        '  *"get providers"*) cat "$T/providers.table" 2>/dev/null;;\n'
        '  *) :;;\n'
        'esac\n')
    (b / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in ("kubectl", "sleep"):
        os.chmod(b / f, 0o755)
    return b


def _env(tmp_path, b, **extra):
    return dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", T=str(tmp_path), **extra)


def _patches(tmp_path):
    p = tmp_path / "patches"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


# ── argocd-app-kick.sh ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("app,rc,expect_patch,clears_state", [
    (BACKOFF, 0, True, True),     # parked in retry backoff: new op + clear operationState
    (FAILED, 0, True, False),     # finished and failed, no backoff: a plain new op is enough
    (RUNNING, 3, False, False),   # an attempt is running now: never interrupt it
    (HEALTHY, 3, False, False),   # healthy: nothing to do
])
def test_kick_decision(tmp_path, app, rc, expect_patch, clears_state):
    b = _fake_bin(tmp_path, app)
    r = subprocess.run(["bash", KICK, "lbc-app"], env=_env(tmp_path, b), capture_output=True, text=True, timeout=30)
    assert r.returncode == rc, r.stdout + r.stderr
    p = _patches(tmp_path)
    assert bool(p) == expect_patch, p
    if expect_patch:
        assert p[0]["operation"]["sync"]["revision"] == "HEAD"
        assert ("status" in p[0] and p[0]["status"]["operationState"] is None) == clears_state


def test_kick_carries_sync_options_and_retry(tmp_path):
    b = _fake_bin(tmp_path, BACKOFF)
    subprocess.run(["bash", KICK, "lbc-app"], env=_env(tmp_path, b), capture_output=True, text=True, timeout=30)
    op = _patches(tmp_path)[0]["operation"]
    assert op["sync"]["syncOptions"] == ["CreateNamespace=true"]
    assert op["retry"]["backoff"]["maxDuration"] == "10m"


def test_kick_unreadable_app_is_rc1(tmp_path):
    b = _fake_bin(tmp_path, BACKOFF)
    (b / "kubectl").write_text("#!/usr/bin/env bash\nexit 1\n")
    r = subprocess.run(["bash", KICK, "lbc-app"], env=_env(tmp_path, b), capture_output=True, text=True, timeout=30)
    assert r.returncode == 1


# ── cloudfront-attach-origin.sh: ALB wait loop ─────────────────────────────────────────
def _attach_bin(tmp_path, app_json, alb_after):
    b = _fake_bin(tmp_path, app_json)
    # aws: ALB missing for the first `alb_after` describe calls, then present; the
    # distribution already points at it, so the script exits 0 right after the wait.
    (b / "aws").write_text(
        '#!/usr/bin/env bash\n'
        'case "$*" in\n'
        '  *"eks update-kubeconfig"*) exit 0;;\n'
        '  *"describe-load-balancers"*)\n'
        '     N=$(cat "$T/n" 2>/dev/null || echo 0); echo $((N+1)) > "$T/n"\n'
        f'     if [ "$N" -lt {alb_after} ]; then echo None; else printf "arn:alb\\tdns\\tinternal\\tactive\\n"; fi;;\n'
        '  *"list-distributions"*) echo E123;;\n'
        '  *"get-distribution "*) echo vo_123;;\n'
        '  *"get-vpc-origin"*) echo arn:alb;;\n'
        '  *) :;;\n'
        'esac\n')
    os.chmod(b / "aws", 0o755)
    return b


def _run_attach(tmp_path, b):
    env = _env(tmp_path, b, HUB_CLUSTER_NAME="hub", AWS_REGION="r", PLATFORM_CONFIG_FILE="/nonexistent")
    return subprocess.run(["bash", ATTACH], env=env, capture_output=True, text=True, timeout=60)


def test_attach_kicks_lbc_in_backoff_at_most_three_times(tmp_path):
    # ALB appears after 40 polls (600 s of fake time): kicks at 120, 180, 240 s, then capped.
    b = _attach_bin(tmp_path, BACKOFF, alb_after=40)
    r = _run_attach(tmp_path, b)
    assert r.returncode == 0, r.stderr
    assert len(_patches(tmp_path)) == 3, r.stderr
    assert "already pointed at the current ALB" in r.stderr
    assert "kick aws-load-balancer-controller-hub: started a fresh sync" in r.stderr


def test_attach_no_kick_before_two_minutes(tmp_path):
    # ALB after 6 polls (90 s): the kick window is never reached.
    b = _attach_bin(tmp_path, BACKOFF, alb_after=6)
    r = _run_attach(tmp_path, b)
    assert r.returncode == 0, r.stderr
    assert _patches(tmp_path) == []
    assert not (tmp_path / "kubectl.calls").exists()


def test_attach_no_kick_when_lbc_healthy(tmp_path):
    b = _attach_bin(tmp_path, HEALTHY, alb_after=20)
    r = _run_attach(tmp_path, b)
    assert r.returncode == 0, r.stderr
    assert _patches(tmp_path) == []
    assert "Healthy, nothing to do" in r.stderr


# ── hub:settle: LBC remediation ────────────────────────────────────────────────────────
def settle_block(text=None):
    tasks = yaml.safe_load(text if text is not None else open(PROVIDER_TF))["tasks"]
    b = tasks["hub:settle"]["cmds"][0]
    b = (b.replace("{{.ROOT_DIR}}", REPO).replace("{{.HUB_CLUSTER_NAME}}", "hub")
          .replace("{{.AWS_REGION}}", "r").replace("{{.MAX_OUTOFSYNC}}", "5")
          .replace("{{.MARK}}", "true"))
    return b


def run_settle(tmp_path, block, app_json, apps_table, providers_table=""):
    b = _fake_bin(tmp_path, app_json)
    (b / "aws").write_text("#!/usr/bin/env bash\nexit 0\n")
    os.chmod(b / "aws", 0o755)
    (tmp_path / "apps.table").write_text(apps_table)
    (tmp_path / "providers.table").write_text(providers_table)
    block = block.replace("/tmp/hub-full-sync-settle.status", str(tmp_path / "status"))
    return subprocess.run(["bash", "-c", block], env=_env(tmp_path, b), capture_output=True, text=True, timeout=120)


# 8 apps out of sync (> MAX_OUTOFSYNC 5), LBC Progressing: the settle keeps polling to timeout.
STUCK = "\n".join(["aws-load-balancer-controller-hub OutOfSync Progressing"] +
                  [f"app{i} OutOfSync Progressing" for i in range(8)]) + "\n"


# Providers Healthy, so only the LBC remediation can patch (R3's crossplane-base one stays off).
PROVIDERS_OK = "provider-aws-iam True True xpkg/iam 5m\n"


def test_settle_kicks_lbc_at_most_three_times(tmp_path):
    r = run_settle(tmp_path, settle_block(), BACKOFF, STUCK, PROVIDERS_OK)
    assert len(_patches(tmp_path)) == 3, r.stdout + r.stderr
    assert "kick aws-load-balancer-controller-hub: started a fresh sync" in r.stdout


def test_settle_no_lbc_kick_when_healthy(tmp_path):
    table = STUCK.replace("aws-load-balancer-controller-hub OutOfSync Progressing",
                          "aws-load-balancer-controller-hub Synced Healthy")
    run_settle(tmp_path, settle_block(), HEALTHY, table, PROVIDERS_OK)
    assert _patches(tmp_path) == []
