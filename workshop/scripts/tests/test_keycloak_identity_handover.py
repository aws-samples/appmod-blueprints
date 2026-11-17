"""kind-kro-ack hub:keycloak-identity-handover: on a hub upgraded from the Crossplane to the ACK
backend of the keycloak client-provisioner identity, set deletionPolicy=Orphan on the old
Crossplane Role and PodIdentityAssociation, read it back, then delete them. Never before the ACK
pair is synced, never a delete without Orphan, a no-op when nothing is left, never fatal.

The task's shell block runs with bash against a fake `kubectl` that keeps object state in files.
No cluster, no AWS.

Run:  python -m pytest workshop/scripts/tests/test_keycloak_identity_handover.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
KRO = yaml.safe_load(open(os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")))["tasks"]
TASK = KRO["hub:keycloak-identity-handover"]
(BLOCK,) = [c["cmd"] for c in TASK["cmds"] if isinstance(c, dict) and "cmd" in c]
H = "acme-hub"
XROLE = f"roles.iam.aws.upbound.io/{H}-keycloak-client-provisioner-role"
XPIA = f"podidentityassociations.eks.aws.upbound.io/{H}-keycloak-client-provisioner"

# State: $ST/<resource with / -> _> exists; its content is the deletionPolicy (or ACK synced status).
FAKE_KUBECTL = r"""#!/usr/bin/env bash
echo "kubectl $*" >> "$LOG"
verb="$1"; r="$2"; f="$ST/$(echo "$r" | tr / _)"
case "$verb" in
  get)
    [ "${KFAIL:-0}" = 1 ] && { echo "error: You must be logged in to the server (Unauthorized)" >&2; exit 1; }
    [ "${KFAIL:-0}" = 2 ] && { echo "exec: executable aws not found" >&2; exit 1; }
    [ -f "$f" ] || { echo "Error from server (NotFound): $r not found" >&2; exit 1; }
    case "$*" in
      *ACK.ResourceSynced*) cat "$f" ;;
      *deletionPolicy*) cat "$f" ;;
    esac ;;
  patch) [ "${PATCH_FAIL:-0}" = 1 ] && exit 1; [ -f "$f" ] && echo Orphan > "$f" ;;
  delete) case " $(cat "$f" 2>/dev/null) " in *Orphan*) rm -f "$f" ;; *) echo DELETED-WITHOUT-ORPHAN >> "$LOG"; rm -f "$f" ;; esac ;;
esac
"""


def _run(tmp_path, crossplane=True, ack="True", patch_fail=False, kfail=False):
    st = tmp_path / "st"
    st.mkdir(exist_ok=True)
    if crossplane:
        for r in (XROLE, XPIA):
            (st / r.replace("/", "_")).write_text("Delete")
    if ack is not None:
        for r in (f"roles.iam.services.k8s.aws/{H}-keycloak-client-provisioner-role",
                  f"podidentityassociations.eks.services.k8s.aws/{H}-keycloak-client-provisioner"):
            (st / r.replace("/", "_")).write_text(ack)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "kubectl").write_text(FAKE_KUBECTL)
    (bindir / "kubectl").chmod(0o755)
    log = tmp_path / "log"
    log.write_text("")
    block = re.sub(r"\{\{\.C_[A-Z]+\}\}", "", BLOCK).replace("{{.ROOT_DIR}}", str(tmp_path)) \
        .replace("{{.HUB_CLUSTER_NAME}}", H)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", LOG=str(log), ST=str(st),
               PATCH_FAIL="1" if patch_fail else "0", KFAIL=str(kfail) if kfail else "0")
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + block], env=env, capture_output=True,
                       text=True, timeout=30)
    return r, log.read_text().splitlines(), st


def test_upgraded_hub_orphans_then_deletes_the_crossplane_pair(tmp_path):
    r, log, st = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "DELETED-WITHOUT-ORPHAN" not in log
    patches = [i for i, ln in enumerate(log) if ln.startswith("kubectl patch")]
    deletes = [i for i, ln in enumerate(log) if ln.startswith("kubectl delete")]
    assert len(patches) == 2 and len(deletes) == 2 and max(patches) < min(deletes), log
    assert all('"deletionPolicy":"Orphan"' in log[i] for i in patches)
    assert not (st / XROLE.replace("/", "_")).exists() and not (st / XPIA.replace("/", "_")).exists()
    # the ACK pair is never touched
    assert not [ln for ln in log if ln.split()[1] in ("patch", "delete")
                and any(t.split("/")[0].endswith(".services.k8s.aws") for t in ln.split()[2:])]


def test_fresh_or_already_handed_over_hub_is_a_no_op(tmp_path):
    r, log, _ = _run(tmp_path, crossplane=False)
    assert r.returncode == 0 and "nothing to hand over" in r.stdout
    assert not [ln for ln in log if ln.split()[1] in ("patch", "delete")]
    r, log, _ = _run(tmp_path)          # first run hands over
    r, log, _ = _run(tmp_path, crossplane=False)  # second run: nothing left
    assert not [ln for ln in log if ln.split()[1] in ("patch", "delete")]


@pytest.mark.parametrize("ack", ["False", None])
def test_nothing_changes_until_ack_holds_the_pair(tmp_path, ack):
    r, log, st = _run(tmp_path, ack=ack)
    assert r.returncode == 0 and "not synced by ACK yet" in r.stdout
    assert not [ln for ln in log if ln.split()[1] in ("patch", "delete")]
    assert (st / XROLE.replace("/", "_")).read_text() == "Delete"


def test_no_delete_when_orphan_could_not_be_set(tmp_path):
    r, log, st = _run(tmp_path, patch_fail=True)
    assert r.returncode == 0 and "could not set deletionPolicy=Orphan" in r.stdout
    assert not [ln for ln in log if ln.startswith("kubectl delete")]
    assert (st / XROLE.replace("/", "_")).exists()


def test_task_is_non_fatal_and_runs_after_keycloak_in_finalize():
    assert [c for c in TASK["cmds"] if isinstance(c, dict) and "cmd" in c][0].get("ignore_error") is True
    fin = [c.get("task") if isinstance(c, dict) else None for c in KRO["install:finalize"]["cmds"]]
    assert fin.index("hub:wait-for-keycloak") < fin.index("hub:keycloak-identity-handover")


@pytest.mark.parametrize("kfail", ["1", "2"])  # Unauthorized; kubeconfig exec plugin missing
def test_a_read_error_is_not_taken_for_absent(tmp_path, kfail):
    r, log, st = _run(tmp_path, kfail=kfail)
    assert r.returncode == 0, r.stderr
    assert "nothing to hand over" not in r.stdout and "could not read" in r.stdout and "Re-run" in r.stdout
    assert not [ln for ln in log if ln.split()[1] in ("patch", "delete")]
    assert (st / XROLE.replace("/", "_")).read_text() == "Delete"


@pytest.mark.skipif(not (shutil.which("task") and shutil.which("yq")), reason="needs go-task and yq")
def test_a_failed_kubeconfig_does_not_stop_the_install(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(os.path.join(REPO, "Taskfile.yaml"), root / "Taskfile.yaml")
    shutil.copytree(os.path.join(REPO, "cluster-providers"), root / "cluster-providers")
    shutil.copytree(os.path.join(REPO, "gitops", "addons", "registry"), root / "gitops" / "addons" / "registry")
    (root / "config.local.yaml").write_text(
        'clusterProvider: kind-kro-ack\nresourcePrefix: acme\naws: {region: us-west-2, accountId: "111122223333"}\n'
        "hub: {clusterName: acme-hub}\nrepo: {url: https://example.invalid/r, revision: main, basepath: gitops/addons/}\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text("#!/bin/sh\necho 'An error occurred (ExpiredToken)' >&2\nexit 255\n")
    (bindir / "kubectl").write_text("#!/bin/sh\necho 'error: no configuration has been provided' >&2\nexit 1\n")
    for f in ("aws", "kubectl"):
        (bindir / f).chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("AWS_PROFILE", "AWS_CONFIG_FILE", "KUBECONFIG")}
    env.update(PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(tmp_path))
    r = subprocess.run([shutil.which("task"), "-d", str(root), "kind-kro-ack:hub:keycloak-identity-handover"],
                       env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert "could not read" in r.stdout + r.stderr
