"""`ray:setup` must create the Pod Identity associations BEFORE the S3 CSI driver addon.

EKS Pod Identity injects credentials at pod admission: driver pods started before the
kube-system/s3-csi-driver-sa association exists have none, and every Mountpoint pod
fails with "Failed to create S3 client". When the addon already exists and the
association is new, the node driver DaemonSet (daemonset/s3-csi-node) is restarted.

Runs the real task with fake `aws`/`kubectl` on PATH that log every call. No AWS.

Run:  python -m pytest workshop/scripts/tests/test_ray_setup_order.py -q
"""
import os
import shutil
import subprocess

import pytest

if not (shutil.which("task") and shutil.which("bash")):
    pytest.skip("go-task/bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RAY = os.path.join(REPO, "cluster-providers", "common", "Taskfile.ray.yaml")

FAKE_AWS = r'''#!/bin/bash
echo "aws $*" >> "$CALLS"
case "$1 $2" in
  "iam get-role") exit 1 ;;
  "eks list-pod-identity-associations")
      if [ -n "${EXISTING_PIA:-}" ]; then echo a-123; else echo None; fi; exit 0 ;;
  "eks update-kubeconfig")
      while [ $# -gt 0 ]; do [ "$1" = "--kubeconfig" ] && echo "apiVersion: v1" > "$2"; shift; done; exit 0 ;;
  "eks describe-addon") [ -n "${ADDON_EXISTS:-}" ]; exit $? ;;
esac
exit 0
'''
FAKE_KUBECTL = (
    '#!/bin/bash\necho "kubectl $*" >> "$CALLS"\n'
    '[ -s "${KUBECONFIG:-}" ] || { echo "no kubeconfig at call time" >&2; exit 1; }\n'
    'exit ${KUBECTL_RC:-0}\n'
)


def _run(tmp_path, **extra_env):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("aws", FAKE_AWS), ("kubectl", FAKE_KUBECTL)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    calls = tmp_path / "calls"
    cfg = tmp_path / "config.local.yaml"  # ray:roles reads privilegedSteps (absent = inline)
    cfg.write_text("resourcePrefix: peeks\n")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", CALLS=str(calls), **extra_env)
    r = subprocess.run(
        ["task", "-t", RAY, "setup", "AWS_REGION=us-west-2", "AWS_ACCOUNT_ID=111111111111",
         "HUB_CLUSTER_NAME=hub", "RESOURCE_PREFIX=peeks", f"ROOT_DIR={REPO}", f"CONFIG_FILE={cfg}"],
        env=env, capture_output=True, text=True, cwd=tmp_path)
    return r, calls.read_text().splitlines() if calls.exists() else []


def _first(lines, needle):
    return next(i for i, l in enumerate(lines) if needle in l)


def test_fresh_install_creates_roles_and_associations_before_addon(tmp_path):
    r, calls = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    addon = _first(calls, "eks create-addon")
    assert _first(calls, "iam create-role") < addon
    pias = [i for i, l in enumerate(calls) if "eks create-pod-identity-association" in l]
    assert len(pias) == 3 and max(pias) < addon
    assert any("--service-account s3-csi-driver-sa" in calls[i] for i in pias)
    assert not any(l.startswith("kubectl") for l in calls)


def test_existing_addon_new_association_restarts_node_driver(tmp_path):
    r, calls = _run(tmp_path, ADDON_EXISTS="1")
    assert r.returncode == 0, r.stderr
    assert not any("eks create-addon" in l for l in calls)
    k = [l for l in calls if l.startswith("kubectl")]
    assert k == ["kubectl -n kube-system rollout restart daemonset/s3-csi-node"]
    assert _first(calls, "eks create-pod-identity-association") < _first(calls, "kubectl")
    assert "could not restart" not in r.stdout  # kubectl saw a real kubeconfig


def test_existing_addon_existing_association_no_restart(tmp_path):
    r, calls = _run(tmp_path, ADDON_EXISTS="1", EXISTING_PIA="1")
    assert r.returncode == 0, r.stderr
    assert not any(l.startswith("kubectl") for l in calls)


def test_restart_failure_is_not_fatal(tmp_path):
    r, _ = _run(tmp_path, ADDON_EXISTS="1", KUBECTL_RC="1")
    assert r.returncode == 0, r.stderr
    assert "could not restart" in r.stdout
