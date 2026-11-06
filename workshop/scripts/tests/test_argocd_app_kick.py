"""Hermetic tests for scripts/argocd-app-kick.sh, the helper hub:settle uses for its
once-only crossplane-base remediation.

Covers:
  * when it patches, and what it patches (a plain `.operation` patch is ignored by Argo CD
    while an operation sits in retry backoff, so the helper must also clear
    status.operationState in that case, and must never interrupt a running attempt);
  * the load balancer controller is NOT kicked any more: neither the ALB wait in
    scripts/cloudfront-attach-origin.sh nor hub:settle (kind-kro-ack) touch it. Its retry is
    already capped at 1m, so a kick bypasses a timer the app does not wait on (PR #1256 review).

Everything runs with bash against fake `kubectl`/`aws` and a no-op `sleep`. No cluster.

Run:  python -m pytest workshop/scripts/tests/test_argocd_app_kick.py -q
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


# ── cloudfront-attach-origin.sh: no LBC kick ───────────────────────────────────────────
def test_attach_does_not_kick_lbc():
    text = open(ATTACH).read()
    assert "argocd-app-kick" not in text
    assert "lbc_kick" not in text


# ── hub:settle: no LBC kick, crossplane-base only ────────────────────────────────────────────────────────
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


def test_settle_never_kicks_lbc(tmp_path):
    # LBC parked in backoff and Progressing for the whole settle; providers Healthy, so the
    # crossplane-base remediation stays off too: no patch at all.
    r = run_settle(tmp_path, settle_block(), BACKOFF, STUCK, PROVIDERS_OK)
    assert _patches(tmp_path) == [], r.stdout + r.stderr
    assert "aws-load-balancer-controller" not in settle_block()
