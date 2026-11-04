"""Hermetic tests for the argocd capability gate of hub:apply-root-appset (kind-kro-ack).

The step polls `aws eks describe-capability` until the argocd capability is ACTIVE before the
10-min wait for its CRDs. The shell block is read from the Taskfile, its go-task variables are
filled in, and it runs with bash against a fake `aws` (scripted statuses) and a no-op `sleep`.
No AWS, no cluster.

Run:  python -m pytest workshop/scripts/tests/test_argocd_capability_wait.py -q
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
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")


def _block():
    cmds = yaml.safe_load(open(TASKFILE))["tasks"]["hub:apply-root-appset"]["cmds"]
    blocks = [c for c in cmds if isinstance(c, str) and "describe-capability" in c]
    assert len(blocks) == 1, blocks
    b = blocks[0].replace("{{.HUB_CLUSTER_NAME}}", "hub").replace("{{.AWS_REGION}}", "r")
    return re.sub(r"\{\{\s*\.C_[A-Z]+\s*\}\}", "", b)


def _run(tmp_path, statuses):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (tmp_path / "statuses").write_text("\n".join(statuses) + "\n")
    # Each call pops the next scripted status; "ERR" = the CLI fails (no output, rc 255).
    (bin_ / "aws").write_text(
        '#!/usr/bin/env bash\n'
        'echo "$*" >> "$T/calls"\n'
        'S=$(head -1 "$T/statuses"); sed -i 1d "$T/statuses"\n'
        '[ "$S" = ERR ] && exit 255\n'
        'echo "${S:-ACTIVE}"\n')
    (bin_ / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in ("aws", "sleep"):
        os.chmod(bin_ / f, 0o755)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", T=str(tmp_path))
    r = subprocess.run(["bash", "-c", _block()], env=env, capture_output=True, text=True, timeout=60)
    calls = (tmp_path / "calls").read_text().splitlines() if (tmp_path / "calls").exists() else []
    return r, calls


def test_waits_until_active(tmp_path):
    r, calls = _run(tmp_path, ["CREATING", "CREATING", "CREATING", "ACTIVE"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(calls) == 4
    assert all("describe-capability --cluster-name hub --capability-name argocd" in c for c in calls)
    assert "wait done (status=ACTIVE)" in r.stdout


def test_stops_on_create_failed(tmp_path):
    r, calls = _run(tmp_path, ["CREATING", "CREATE_FAILED"])
    assert r.returncode == 1 and len(calls) == 2
    assert "argocd capability is CREATE_FAILED" in r.stdout


def test_three_read_errors_fall_through_to_the_crd_wait(tmp_path):
    r, calls = _run(tmp_path, ["ERR", "ERR", "ERR", "ACTIVE"])
    assert r.returncode == 0 and len(calls) == 3
    assert "status=unknown" in r.stdout


def test_budget_is_bounded(tmp_path):
    r, calls = _run(tmp_path, ["CREATING"] * 400)
    assert r.returncode == 0  # falls through to the CRD wait, which then reports the failure
    assert len(calls) == 360  # 3600 s / 10 s
