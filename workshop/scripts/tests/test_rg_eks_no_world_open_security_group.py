"""Static checks on the EksCluster RGD (rg-eks.yaml): no world-open security group.

The RGD used to create `<cluster>-ingress-http` / `<cluster>-ingress-https` security groups with one
ingress rule each from 0.0.0.0/0. Nothing attached them: the platform ALB uses the security group
the load balancer controller manages from IngressClassParams.inboundCIDRs (ingress-class-alb), and
the only reference to their IDs was the `ingress_security_groups` cluster-secret annotation, which
no chart, registry entry or task reads. So every hub and kro spoke carried two unattached
world-open groups, and attaching one later would silently bypass the source-IP allowlist
(albInboundCidrs / spokeAlbInboundCidrs). The groups are gone; the annotation key stays, empty,
so the metadata contract keeps its shape (the other providers write it from config
`ingressSecurityGroups`, default "").

kro/CEL cannot be rendered here, so these are parses of the RGD file.

Run:  python -m pytest workshop/scripts/tests/test_rg_eks_no_world_open_security_group.py -q
"""
import json
import os
import re

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "eks",
                   "rg-eks.yaml")
WORLD = {"0.0.0.0/0", "::/0"}


def _rgd():
    with open(RGD) as f:
        return yaml.safe_load(f)


def _resources():
    return _rgd()["spec"]["resources"]


def _resource(rid):
    for r in _resources():
        if r.get("id") == rid:
            return r
    raise AssertionError(f"resource id {rid} not found")


def test_no_security_group_allows_ingress_from_anywhere():
    open_groups = []
    for r in _resources():
        t = r.get("template", {})
        if t.get("kind") != "SecurityGroup":
            continue
        for rule in t.get("spec", {}).get("ingressRules") or []:
            cidrs = {x.get("cidrIP") for x in rule.get("ipRanges") or []}
            cidrs |= {x.get("cidrIPv6") for x in rule.get("ipv6Ranges") or []}
            if cidrs & WORLD:
                open_groups.append((r["id"], rule.get("fromPort"), sorted(cidrs & WORLD)))
    assert not open_groups, f"world-open ingress in rg-eks.yaml: {open_groups}"


def test_every_status_reference_names_a_declared_resource():
    # Guards the removal: a leftover ${<id>.status...} on a deleted node would fail the RGD.
    # Walks the parsed YAML, so commented-out nodes are ignored.
    def strings(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from strings(v)
        elif isinstance(node, list):
            for v in node:
                yield from strings(v)
        elif isinstance(node, str):
            yield node

    ids = {r["id"] for r in _resources()}
    refs = {m for s in strings(_rgd()) for m in re.findall(r"\b([A-Za-z][A-Za-z0-9]*)\.status\.", s)}
    refs -= {"schema"}
    assert refs <= ids, f"references to undeclared resources: {sorted(refs - ids)}"


def test_ingress_security_groups_key_is_kept_empty_on_both_paths():
    ann = _resource("argocdSecret")["template"]["metadata"]["annotations"]
    assert ann["ingress_security_groups"] == ""
    cfg = _resource("clusterConfigK8sSecretFleet")["template"]["stringData"]["config"]
    meta = json.loads(json.loads(cfg)["metadata"])
    assert meta["ingress_security_groups"] == ""
