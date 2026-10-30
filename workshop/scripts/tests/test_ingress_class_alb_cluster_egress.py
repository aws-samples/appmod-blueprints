"""`helm template` tests for the ingress-class-alb chart's `clusterEgressCidrs` value.

The registry (gitops/addons/registry/core.yaml) passes the cluster-secret annotation
`nat_egress_cidrs` (the provider-written NAT egress IPs of the cluster) as
`clusterEgressCidrs`. The chart must append it to `inboundCidrs` + `extraInboundCidrs`
ONLY when that allowlist is non-empty, so:
  - no allowlist (workshop / CloudFront / any install today) -> render unchanged, the value is
    ignored and the ALB stays open;
  - allowlist, no egress value -> render unchanged;
  - allowlist + egress value -> egress appended, existing entries kept, no duplicate.

Run:  python -m pytest workshop/scripts/tests/test_ingress_class_alb_cluster_egress.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "ingress-class-alb")
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry", "core.yaml")
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")

NAT = "203.0.113.200/32"
MODES = {
    "auto": [],
    "oss": ["--set", "controllerMode=oss"],
    "cloudfront": ["--set", "scheme=internal", "--set", "loadBalancerName=acme-hub-platform"],
}


def _render(*args):
    res = subprocess.run([HELM, "template", "x", CHART, *args], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stderr
    return res.stdout


def _cidrs(rendered):
    for doc in yaml.safe_load_all(rendered):
        if doc and doc.get("kind") == "IngressClassParams":
            return doc["spec"].get("inboundCIDRs")
    pytest.fail("no IngressClassParams rendered")


@needs_helm
@pytest.mark.parametrize("mode", sorted(MODES))
def test_no_allowlist_ignores_the_egress_value(mode):
    base = _render(*MODES[mode])
    assert _cidrs(base) is None
    assert _render(*MODES[mode], "--set-string", f"clusterEgressCidrs={NAT}") == base
    assert _render(*MODES[mode], "--set-string", "clusterEgressCidrs=") == base


@needs_helm
def test_allowlist_without_egress_is_unchanged():
    out = _render("--set", "inboundCidrs={203.0.113.0/25,203.0.113.10/32}")
    assert _cidrs(out) == ["203.0.113.0/25", "203.0.113.10/32"]
    assert _render("--set", "inboundCidrs={203.0.113.0/25,203.0.113.10/32}",
                   "--set-string", "clusterEgressCidrs=") == out


@needs_helm
def test_egress_is_appended_after_inbound_and_extra():
    out = _render("--set", "inboundCidrs={203.0.113.0/25}",
                  "--set-string", "extraInboundCidrs=203.0.113.10/32\\,203.0.113.11/32",
                  "--set-string", f"clusterEgressCidrs={NAT}")
    assert _cidrs(out) == ["203.0.113.0/25", "203.0.113.10/32", "203.0.113.11/32", NAT]


@needs_helm
def test_extra_only_allowlist_also_gets_the_egress():
    out = _render("--set-string", "extraInboundCidrs=203.0.113.10/32",
                  "--set-string", f"clusterEgressCidrs={NAT}")
    assert _cidrs(out) == ["203.0.113.10/32", NAT]


@needs_helm
def test_egress_already_listed_is_not_duplicated():
    out = _render("--set", f"inboundCidrs={{203.0.113.0/25,{NAT}}}",
                  "--set-string", f"clusterEgressCidrs={NAT}")
    assert _cidrs(out) == ["203.0.113.0/25", NAT]


@needs_helm
def test_egress_csv_and_list_forms_with_blanks_and_repeats():
    csv = _render("--set", "inboundCidrs={203.0.113.0/25}",
                  "--set-string", "clusterEgressCidrs= 203.0.113.200/32\\,\\,203.0.113.201/32\\,203.0.113.200/32 ")
    lst = _render("--set", "inboundCidrs={203.0.113.0/25}",
                  "--set", "clusterEgressCidrs={203.0.113.200/32,203.0.113.201/32}")
    want = ["203.0.113.0/25", "203.0.113.200/32", "203.0.113.201/32"]
    assert _cidrs(csv) == want and _cidrs(lst) == want


def test_registry_passes_the_annotation_under_a_distinct_key():
    with open(REGISTRY) as f:
        entry = yaml.safe_load(f)["ingress-class-alb"]
    vo = entry["valuesObject"]
    assert vo["clusterEgressCidrs"] == '{{default "" (index .metadata.annotations "nat_egress_cidrs")}}'
    # The overlay owns the allowlist itself: valuesObject wins over value files in ArgoCD,
    # so the registry must never set these keys.
    assert "inboundCidrs" not in vo and "extraInboundCidrs" not in vo
