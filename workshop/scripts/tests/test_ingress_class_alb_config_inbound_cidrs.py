"""`helm template` tests for the ingress-class-alb chart's `configInboundCidrs` value.

`configInboundCidrs` carries the install-time source-IP allowlist that `config.yaml`
(`albInboundCidrs`) sets for the shared "platform" ALB. The registry
(gitops/addons/registry/core.yaml) passes the cluster-secret annotation `config_inbound_cidrs`
(written by the kind-kro-ack / kind-crossplane providers at install) as `configInboundCidrs`.
The chart CONCATENATES it with `inboundCidrs` + `extraInboundCidrs` (so the install-time source
and a post-install fleet overlay add up, neither overriding the other), and the NAT egress IPs
are still appended once that combined allowlist is non-empty. It uses its OWN chart key because
the registry `valuesObject` wins over overlay value files in ArgoCD: reusing `inboundCidrs`
here would clobber an operator's overlay list.

Contract:
  - no key / empty  -> render unchanged, the ALB stays open (byte-identical to no-config);
  - config only     -> rendered into IngressClassParams.spec.inboundCIDRs;
  - config + overlay inboundCidrs/extraInboundCidrs -> union of all three;
  - config present  -> NAT egress (clusterEgressCidrs) is appended (allowlist now non-empty),
                       deduplicated against the config list.

Run:  python -m pytest workshop/scripts/tests/test_ingress_class_alb_config_inbound_cidrs.py -q
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
def test_no_config_key_renders_unchanged(mode):
    base = _render(*MODES[mode])
    assert _cidrs(base) is None
    # An empty value is identical to the key being absent: the ALB stays open.
    assert _render(*MODES[mode], "--set-string", "configInboundCidrs=") == base


@needs_helm
def test_config_only_is_rendered():
    out = _render("--set", "configInboundCidrs={203.0.113.0/24,203.0.113.5/32}")
    assert _cidrs(out) == ["203.0.113.0/24", "203.0.113.5/32"]


@needs_helm
def test_config_unions_with_overlay_inbound_and_extra():
    # The install-time config value and the fleet-overlay keys ADD UP (order:
    # inboundCidrs, then extraInboundCidrs, then configInboundCidrs).
    out = _render("--set", "inboundCidrs={203.0.113.0/25}",
                  "--set-string", "extraInboundCidrs=203.0.113.10/32",
                  "--set", "configInboundCidrs={203.0.113.50/32}")
    assert _cidrs(out) == ["203.0.113.0/25", "203.0.113.10/32", "203.0.113.50/32"]


@needs_helm
def test_config_csv_form_is_split():
    out = _render("--set-string", "configInboundCidrs=203.0.113.0/24\\,203.0.113.60/32")
    assert _cidrs(out) == ["203.0.113.0/24", "203.0.113.60/32"]


@needs_helm
def test_config_alone_triggers_the_egress_append():
    # With only configInboundCidrs set the allowlist is non-empty, so the hub NAT
    # (clusterEgressCidrs) is appended -- the install-time allowlist keeps in-cluster SSO.
    out = _render("--set", "configInboundCidrs={203.0.113.0/24}",
                  "--set-string", f"clusterEgressCidrs={NAT}")
    assert _cidrs(out) == ["203.0.113.0/24", NAT]


@needs_helm
def test_egress_not_duplicated_when_already_in_config():
    out = _render("--set", f"configInboundCidrs={{203.0.113.0/24,{NAT}}}",
                  "--set-string", f"clusterEgressCidrs={NAT}")
    assert _cidrs(out) == ["203.0.113.0/24", NAT]


@needs_helm
def test_egress_still_ignored_without_any_allowlist():
    # configInboundCidrs empty and no overlay keys -> egress value is ignored, ALB open.
    base = _render()
    assert _render("--set-string", "configInboundCidrs=",
                   "--set-string", f"clusterEgressCidrs={NAT}") == base


def test_registry_passes_the_config_annotation_under_a_distinct_key():
    with open(REGISTRY) as f:
        entry = yaml.safe_load(f)["ingress-class-alb"]
    vo = entry["valuesObject"]
    assert vo["configInboundCidrs"] == \
        '{{default "" (index .metadata.annotations "config_inbound_cidrs")}}'
    # The overlay still owns inboundCidrs/extraInboundCidrs: valuesObject wins over value files
    # in ArgoCD, so the registry must never set those two (it would clobber the overlay list).
    assert "inboundCidrs" not in vo and "extraInboundCidrs" not in vo
