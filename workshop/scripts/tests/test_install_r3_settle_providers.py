"""Hermetic tests for install perf R3: hub:settle (kind-kro-ack) must not exit before the
Crossplane providers are Healthy or the crossplane-base remediation has had its chance.

Before: the settle broke out as soon as <= MAX_OUTOFSYNC apps were out of sync, which can be
true at 3 s on a fresh hub (few apps, providers 0/0), so the remediation (>= 300 s) never ran.
With the providers gate skipped on the kind-kro-ack spoke path, nothing else ran it.

The block runs with bash against fake `kubectl`/`aws` and a no-op `sleep`. No cluster.

Run:  python -m pytest workshop/scripts/tests/test_install_r3_settle_providers.py -q
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
PROVIDER_TF = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")

SETTLED = "argocd-hub Synced Healthy\ncrossplane-base-hub Synced Healthy\n"
CB_OUT = "argocd-hub Synced Healthy\ncrossplane-base-hub OutOfSync Progressing\n"
PROV_OK = "provider-aws-iam True True xpkg/iam 5m\nprovider-aws-eks True True xpkg/eks 5m\n"
PROV_BAD = "provider-aws-iam True False xpkg/iam 1m\nprovider-aws-eks True True xpkg/eks 1m\n"
CB_BACKOFF = {"spec": {"syncPolicy": {"retry": {"limit": -1}}},
              "status": {"health": {"status": "Progressing"},
                         "operationState": {"phase": "Running", "finishedAt": "2026-01-01T00:00:00Z"}}}


def settle_block():
    b = yaml.safe_load(open(PROVIDER_TF))["tasks"]["hub:settle"]["cmds"][0]
    return (b.replace("{{.ROOT_DIR}}", REPO).replace("{{.HUB_CLUSTER_NAME}}", "hub")
             .replace("{{.AWS_REGION}}", "r").replace("{{.MAX_OUTOFSYNC}}", "5")
             .replace("{{.MARK}}", "true"))


def run(tmp_path, apps, providers, app_json=CB_BACKOFF, providers_after=None, errexit=False):
    """providers: table returned by `get providers`; providers_after=(n, table) switches
    the table after n provider reads."""
    b = tmp_path / "bin"
    b.mkdir()
    (tmp_path / "apps.table").write_text(apps)
    (tmp_path / "prov0").write_text(providers)
    n_switch, later = providers_after or (10_000, providers)
    (tmp_path / "prov1").write_text(later)
    (tmp_path / "app.json").write_text(json.dumps(app_json))
    (b / "kubectl").write_text(
        '#!/usr/bin/env bash\n'
        'case "$*" in\n'
        '  *"get applications.argoproj.io"*"-o json"*) cat "$T/app.json";;\n'
        '  *"get applications.argoproj.io"*) cat "$T/apps.table";;\n'
        '  *"patch applications.argoproj.io"*) shift $(( $# - 1 )); echo "$1" >> "$T/patches";;\n'
        '  *"get providers"*) N=$(cat "$T/pn" 2>/dev/null || echo 0); echo $((N+1)) > "$T/pn"\n'
        f'     if [ "$N" -lt {n_switch} ]; then cat "$T/prov0"; else cat "$T/prov1"; fi;;\n'
        'esac\nexit 0\n')
    (b / "aws").write_text("#!/usr/bin/env bash\nexit 0\n")
    (b / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in ("kubectl", "aws", "sleep"):
        os.chmod(b / f, 0o755)
    block = settle_block().replace("/tmp/hub-full-sync-settle.status", str(tmp_path / "status"))
    if errexit:  # the Taskfile sets errexit/nounset/pipefail for every cmd, as go-task runs it
        block = "set -euo pipefail\n" + block
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", T=str(tmp_path))
    r = subprocess.run(["bash", "-c", block], env=env, capture_output=True, text=True, timeout=120)
    patches = [json.loads(l) for l in (tmp_path / "patches").read_text().splitlines()] \
        if (tmp_path / "patches").exists() else []
    m = re.findall(r"\[(\d+)s\]", r.stdout)
    last = int(m[-1]) if m else -1
    return r, patches, last


def test_providers_zero_at_start_waits_for_remediation(tmp_path):
    # The B/t17 case: apps within tolerance at once, no providers yet.
    r, patches, last = run(tmp_path, SETTLED, "")
    assert "Hub settled" in r.stdout, r.stdout
    assert last == 300, r.stdout          # before R3: exited at [0s]
    assert "Force-syncing crossplane-base" in r.stdout
    assert (tmp_path / "status").read_text().strip() == "ok"


def test_remediation_clears_retry_backoff(tmp_path):
    r, patches, _ = run(tmp_path, CB_OUT, "")
    assert len(patches) == 1, r.stdout
    assert patches[0]["status"]["operationState"] is None
    assert patches[0]["operation"]["retry"] == {"limit": -1}


def test_providers_healthy_exits_at_once(tmp_path):
    r, patches, last = run(tmp_path, SETTLED, PROV_OK)
    assert last == 0, r.stdout
    assert patches == []
    assert "all 2 Crossplane providers Healthy" in r.stdout


def test_exits_when_providers_turn_healthy_before_5min(tmp_path):
    # providers appear Healthy on the 5th read (each poll reads once): exit at [120s]
    r, patches, last = run(tmp_path, SETTLED, "", providers_after=(4, PROV_OK))
    assert last == 120, r.stdout
    assert patches == []


def test_final_line_names_unhealthy_provider(tmp_path):
    r, _, _ = run(tmp_path, SETTLED, PROV_BAD)
    assert "providers still not Healthy: provider-aws-iam" in r.stdout, r.stdout
    assert "all 2 Crossplane providers Healthy" not in r.stdout


CB_RUNNING = {"spec": {}, "status": {"health": {"status": "Progressing"},
                                     "operationState": {"phase": "Running"}}}


@pytest.mark.parametrize("app_json", [CB_RUNNING, CB_BACKOFF])
def test_remediation_survives_errexit(tmp_path, app_json):
    # Live E2E on this branch: the helper answered "not needed" (exit 3) and, under the
    # Taskfile's errexit, the bare KOUT=$(...) aborted hub:settle at 300 s, leaving its
    # status at "running". The remediation must never end the settle.
    r, _, last = run(tmp_path, CB_OUT, "", app_json=app_json, errexit=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Force-syncing crossplane-base" in r.stdout
    assert last >= 300, r.stdout
    assert "Hub settled" in r.stdout and "Healthyyes" not in r.stdout
    assert (tmp_path / "status").read_text().strip() == "ok"


def test_settled_line_names_provider_state(tmp_path):
    r, _, _ = run(tmp_path, SETTLED, PROV_OK)
    assert "providers Healthy)." in r.stdout, r.stdout
