"""Wiring tests for a spoke's OWN NAT reaching its OWN ingress-class-alb allowlist (option a).

A spoke runs its own `ingress-class-alb` (its own internet-facing `platform` ALB). For a spoke
allowlist to include the spoke's own NAT EIP automatically, the NAT CIDR is threaded, with the kro
RGD as the single writer:

  rg-vpc.yaml           Vpc status.natEgressCidrs = CEL "<eip.publicIP>/32" (comma-separated string)
    -> rg-eks-vpc.yaml  EksclusterWithVpc passes ${vpc.status.natEgressCidrs} into the nested
                        EksCluster spec.natEgressCidrs
      -> rg-eks.yaml     EksCluster schema field natEgressCidrs, stamped into the spoke cluster
                         secret as the `nat_egress_cidrs` annotation (default fleet-secret path =
                         clusterConfigK8sSecretFleet metadata; and the createArgocdClusterSecret
                         parity path = argocdSecret annotations)
        -> registry core.yaml  ingress-class-alb valuesObject.clusterEgressCidrs reads
                               `nat_egress_cidrs` (shared hub+spoke entry)
          -> chart        appends clusterEgressCidrs to the allowlist ONLY when one is set.

These are static parses of the RGDs/registry (kro/CEL cannot be rendered here) plus helm-template
proofs that, without an allowlist, the spoke render is byte-identical (the NAT is ignored).

Run:  python -m pytest workshop/scripts/tests/test_spoke_nat_egress_wiring.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EKS = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "eks")
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry", "core.yaml")
CHART = os.path.join(REPO, "gitops", "addons", "charts", "ingress-class-alb")
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")


def _rgd(name):
    with open(os.path.join(EKS, name)) as f:
        return yaml.safe_load(f)


def _resource(rgd, rid):
    for r in rgd["spec"]["resources"]:
        if r.get("id") == rid:
            return r
    raise AssertionError(f"resource id {rid} not found")


# --- the single-writer thread, node by node -------------------------------------------------
def test_vpc_status_exposes_nat_egress_as_comma_string():
    vpc = _rgd("rg-vpc.yaml")
    expr = vpc["spec"]["schema"]["status"]["natEgressCidrs"]
    # CSV string (not a list literal) because the consumers read a comma-separated value and
    # managed kro CEL has no join().
    assert expr == '${eip1.status.publicIP + "/32"}', expr
    assert not expr.lstrip("$").startswith("{["), "must not be a list literal"


def test_eksclusterwithvpc_passes_nat_into_the_nested_ekscluster_spec():
    wrap = _rgd("rg-eks-vpc.yaml")
    eks = _resource(wrap, "eks")
    assert eks["template"]["spec"]["natEgressCidrs"] == "${vpc.status.natEgressCidrs}"
    # and still surfaces it in its own status (unchanged)
    assert wrap["spec"]["schema"]["status"]["natEgressCidrs"] == "${vpc.status.natEgressCidrs}"


def test_ekscluster_schema_declares_nat_egress_cidrs():
    eks = _rgd("rg-eks.yaml")
    field = eks["spec"]["schema"]["spec"]["natEgressCidrs"]
    assert isinstance(field, str) and field.startswith("string"), field


def test_default_fleet_secret_path_stamps_the_annotation():
    # createArgocdClusterSecret=="false" (the default): clusterConfigK8sSecretFleet writes the
    # <cluster>/config metadata that ESO turns into the spoke cluster-secret annotations.
    eks = _rgd("rg-eks.yaml")
    cfg = _resource(eks, "clusterConfigK8sSecretFleet")["template"]["stringData"]["config"]
    assert '"nat_egress_cidrs":"${schema.spec.natEgressCidrs}"'.replace('"', '\\"') in cfg \
        or '\\"nat_egress_cidrs\\":\\"${schema.spec.natEgressCidrs}\\"' in cfg, \
        "nat_egress_cidrs not stamped into the fleet-secret metadata"


def test_parity_argocd_secret_path_stamps_the_annotation():
    # createArgocdClusterSecret=="true" (parity path): the RGD-written cluster Secret annotations.
    eks = _rgd("rg-eks.yaml")
    ann = _resource(eks, "argocdSecret")["template"]["metadata"]["annotations"]
    assert ann.get("nat_egress_cidrs") == "${schema.spec.natEgressCidrs}"


def test_registry_feeds_nat_egress_to_clusterEgressCidrs_for_any_cluster():
    with open(REGISTRY) as f:
        vo = yaml.safe_load(f)["ingress-class-alb"]["valuesObject"]
    # shared hub+spoke entry: a spoke's own nat_egress_cidrs annotation -> clusterEgressCidrs.
    assert vo["clusterEgressCidrs"] == '{{default "" (index .metadata.annotations "nat_egress_cidrs")}}'


# --- helm: a spoke ALB without an allowlist is unchanged; with one, the NAT is appended -------
def _render(*args):
    res = subprocess.run([HELM, "template", "x", CHART, *args], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return res.stdout


def _cidrs(rendered):
    for doc in yaml.safe_load_all(rendered):
        if doc and doc.get("kind") == "IngressClassParams":
            return doc["spec"].get("inboundCIDRs")
    pytest.fail("no IngressClassParams rendered")


@needs_helm
def test_spoke_nat_ignored_without_allowlist_byte_identical():
    # oss controller = the spoke's forced mode; internet-facing (spokes have no domain).
    base = _render("--set", "controllerMode=oss")
    assert _cidrs(base) is None
    assert _render("--set", "controllerMode=oss",
                   "--set-string", "clusterEgressCidrs=203.0.113.201/32") == base


@needs_helm
def test_spoke_nat_appended_once_an_allowlist_is_set():
    out = _render("--set", "controllerMode=oss",
                  "--set", "inboundCidrs={203.0.113.0/24}",
                  "--set-string", "clusterEgressCidrs=203.0.113.201/32")
    assert _cidrs(out) == ["203.0.113.0/24", "203.0.113.201/32"]
