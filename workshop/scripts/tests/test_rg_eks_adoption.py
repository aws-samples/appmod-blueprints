"""Hermetic test for the EksCluster RGD (rg-eks.yaml): every ACK resource it creates is
`adopt-or-create`.

The hub self-adoption pivot (`kind-kro-ack:hub:pivot`, the last step of the workshop install)
re-applies the hub's EksCluster on the hub itself, where every AWS resource of the graph
already exists. An ACK node without adopt-or-create makes the hub's ACK call Create, which
fails "already exists" and sets ACK.Terminal, so the pivot's adoption gate (every kro-owned
ACK child synced) can never pass. The RGD is read as YAML; no cluster, no AWS.

Run:  python -m pytest workshop/scripts/tests/test_rg_eks_adoption.py -q
"""
import os

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.path.join(
    REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "eks", "rg-eks.yaml")


def test_every_ack_node_is_adopt_or_create():
    resources = yaml.safe_load(open(RGD))["spec"]["resources"]
    ack = [r for r in resources if ".services.k8s.aws/" in r["template"].get("apiVersion", "")]
    assert ack, "no ACK nodes found"
    create_only = [
        f'{r["id"]} ({r["template"]["kind"]})' for r in ack
        if ((r["template"].get("metadata") or {}).get("annotations") or {})
        .get("services.k8s.aws/adoption-policy") != "adopt-or-create"]
    assert create_only == []
