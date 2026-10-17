"""Static test for the CICDPipeline RGD's EventBus PodDisruptionBudget: a node that hosts
EventBus pods can still be drained, and the JetStream EventBus keeps quorum while it is.

The PDB (`eventbuspdb` in the CICDPipeline RGD) covers the app's JetStream EventBus pods
(`controller: eventbus-controller`), whose replica count comes from the cicd-pipeline
template's EventBus manifest. With `maxUnavailable: 0` the eviction API refuses every
eviction, so EKS Auto Mode / Karpenter / `kubectl drain` can never empty such a node:
not for consolidation or expiry, and not when the node is broken and its NodeClaim is
deleted to replace it.

Run:  python -m pytest workshop/scripts/tests/test_cicd_eventbus_pdb.py -q
Set CICD_RGD=<path> to run the same checks against another copy of the RGD.
"""
import math
import os

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.environ.get("CICD_RGD") or os.path.join(
    REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests",
    "cicd-pipeline", "cicd-pipeline.yaml")
BUS = os.path.join(REPO, "platform", "backstage", "templates", "cicd-pipeline", "skeleton",
                   "manifests", "bus.yaml")


def _pdb():
    with open(RGD) as f:
        rgd = yaml.safe_load(f)
    res = [r for r in rgd["spec"]["resources"] if r.get("id") == "eventbuspdb"]
    assert len(res) == 1, "no eventbuspdb resource in the CICDPipeline RGD"
    return res[0]["template"]["spec"]


def _replicas():
    with open(BUS) as f:
        bus = next(d for d in yaml.safe_load_all(f) if d and d.get("kind") == "EventBus")
    return int(bus["spec"]["jetstream"]["replicas"])


def _allowed(spec, replicas):
    """Evictions the PDB allows with every pod healthy (as the disruption controller computes)."""
    if "maxUnavailable" in spec:
        v = spec["maxUnavailable"]
        return math.ceil(replicas * int(v[:-1]) / 100) if isinstance(v, str) else int(v)
    v = spec["minAvailable"]
    need = math.ceil(replicas * int(v[:-1]) / 100) if isinstance(v, str) else int(v)
    return replicas - need


def test_pdb_selects_the_eventbus_pods():
    assert _pdb()["selector"]["matchLabels"] == {"controller": "eventbus-controller"}


def test_a_node_with_eventbus_pods_can_be_drained():
    allowed = _allowed(_pdb(), _replicas())
    assert allowed >= 1, f"the PDB allows {allowed} evictions: no node hosting an EventBus pod can ever drain"


def test_a_drain_keeps_jetstream_quorum():
    replicas = _replicas()
    allowed = _allowed(_pdb(), replicas)
    assert replicas - allowed >= replicas // 2 + 1, f"{allowed} of {replicas} may go at once: quorum lost"


def test_a_pod_that_is_not_ready_never_blocks_the_drain():
    # The default (IfHealthyBudget) keeps a NotReady pod on a failing node whenever the
    # budget is already short, which is exactly when that node needs replacing.
    assert _pdb().get("unhealthyPodEvictionPolicy") == "AlwaysAllow"
