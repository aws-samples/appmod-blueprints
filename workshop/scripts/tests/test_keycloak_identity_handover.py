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
    [ -f "$f" ] || exit 1
    case "$*" in
      *ACK.ResourceSynced*) cat "$f" ;;
      *deletionPolicy*) cat "$f" ;;
    esac ;;
  patch) [ "${PATCH_FAIL:-0}" = 1 ] && exit 1; [ -f "$f" ] && echo Orphan > "$f" ;;
  delete) case " $(cat "$f" 2>/dev/null) " in *Orphan*) rm -f "$f" ;; *) echo DELETED-WITHOUT-ORPHAN >> "$LOG"; rm -f "$f" ;; esac ;;
esac
"""


def _run(tmp_path, crossplane=True, ack="True", patch_fail=False):
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
               PATCH_FAIL="1" if patch_fail else "0")
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
    assert not [ln for ln in log if ("patch" in ln or "delete" in ln) and "services.k8s.aws" in ln]


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
