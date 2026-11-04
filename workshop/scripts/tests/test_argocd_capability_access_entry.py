"""Hermetic tests for the Argo CD capability nodes of the EksCluster RGD (rg-eks.yaml).

1. The capability's AccessEntry must declare the two policies EKS associates when it creates
   the Argo CD capability (AmazonEKSArgoCDClusterPolicy, cluster scope; AmazonEKSArgoCDPolicy,
   namespace "argocd"). ACK treats accessPolicies as the complete set and disassociates
   anything else, so leaving them out made ACK strip them ~5 min after create (int1104,
   int1105 CloudTrail).
2. The Capability node must depend on the ekscluster node (clusterName from
   ${ekscluster.spec.name}), so kro creates it only once the cluster is ACTIVE. Without the
   dependency ACK called CreateCapability during cluster creation and its error backoff
   delayed the real create by ~10 min after ACTIVE (int1105).

The RGD is read as YAML; no cluster, no AWS.

Run:  python -m pytest workshop/scripts/tests/test_argocd_capability_access_entry.py -q
"""
import os

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.path.join(
    REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "eks", "rg-eks.yaml")
POLICY = "arn:aws:eks::aws:cluster-access-policy/"


def _nodes():
    return {r["id"]: r for r in yaml.safe_load(open(RGD))["spec"]["resources"]}


def _policies(node):
    out = set()
    for p in node["template"]["spec"]["accessPolicies"]:
        scope = p["accessScope"]
        out.add((p["policyARN"], scope["type"], tuple(scope.get("namespaces") or ())))
    return out


def test_argocd_capability_access_entry_declares_eks_default_policies():
    node = _nodes()["argocdCapabilityAccessEntry"]
    assert node["template"]["kind"] == "AccessEntry"
    assert _policies(node) == {
        (POLICY + "AmazonEKSClusterAdminPolicy", "cluster", ()),
        (POLICY + "AmazonEKSArgoCDClusterPolicy", "cluster", ()),
        (POLICY + "AmazonEKSArgoCDPolicy", "namespace", ("argocd",)),
    }


def test_argocd_capability_access_entry_targets_the_capability_role():
    spec = _nodes()["argocdCapabilityAccessEntry"]["template"]["spec"]
    assert spec["principalARN"] == "${argocdCapabilityRole.status.ackResourceMetadata.arn}"
    assert _nodes()["argocdCapability"]["template"]["spec"]["roleARN"] == \
        "${argocdCapabilityRole.status.ackResourceMetadata.arn}"


def test_argocd_capability_namespace_matches_policy_scope():
    # The namespace-scoped policy is pinned to "argocd", the EKS default. If the Capability
    # ever sets configuration.argoCD.namespace, the access entry scope must follow it.
    cfg = _nodes()["argocdCapability"]["template"]["spec"]["configuration"]["argoCD"]
    assert cfg.get("namespace", "argocd") == "argocd"


def test_ack_capability_access_entry_still_declares_its_policies():
    # Unchanged behaviour: the ACK capability entry already used this pattern.
    assert _policies(_nodes()["ackCapabilityAccessEntry"]) == {
        (POLICY + "AmazonEKSACKPolicy", "cluster", ()),
        (POLICY + "AmazonEKSSecretReaderPolicy", "cluster", ()),
    }


@pytest.mark.parametrize("cap", ["argocdCapability", "ackCapability", "kroCapability"])
def test_capabilities_wait_for_active_cluster(cap):
    nodes = _nodes()
    assert nodes["ekscluster"]["readyWhen"] == ['${ekscluster.status.status == "ACTIVE"}']
    assert nodes[cap]["template"]["spec"]["clusterName"] == "${ekscluster.spec.name}"


def test_other_access_entries_unchanged():
    # Only the capability entry gains policies; the cluster-admin entries keep exactly one.
    nodes = _nodes()
    for nid in ("accessEntry", "accessEntryArgocdCapability", "accessEntryAdmin",
                "accessEntryAdminInstance"):
        assert _policies(nodes[nid]) == {(POLICY + "AmazonEKSClusterAdminPolicy", "cluster", ())}, nid
