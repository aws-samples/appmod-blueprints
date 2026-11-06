"""The hub's Crossplane default ManagedResourceActivationPolicy must not activate everything.

gitops/addons/registry/platform.yaml passes `provider.defaultActivations` to the Crossplane
chart, which turns it into the `default` MRAP (`--activation` args of the init container).
The chart default `["*"]` makes every provider install both CRD variants of every managed
resource (`*.aws.upbound.io` and the namespaced `*.aws.m.upbound.io`). On a fresh hub the
188 unused `.m.` CRDs land in the same minutes as the first Argo CD sync and feed the API
server 429 storm that delays the load balancer controller (and the platform ALB).

These tests pin that:
  - the activations are set, and are not a catch-all;
  - no namespaced `.aws.m.upbound.io` managed resource gets activated;
  - every managed-resource API group this repo references is still activated (otherwise its
    CRD would never be installed and the composition / kro graph using it would break).

Patterns are matched the way Crossplane does (Go filepath.Match on the MRD name, i.e.
`<plural>.<group>`); fnmatch is equivalent for names without '/'.

Run:  python -m pytest workshop/scripts/tests/test_crossplane_default_activations.py -q
"""
import fnmatch
import os
import re

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry", "platform.yaml")
# Managed-resource API groups of the providers the platform installs.
MR_GROUP = re.compile(r"\b([a-z0-9-]+\.(?:aws(?:\.m)?\.upbound\.io|kubernetes(?:\.m)?\.crossplane\.io))/v[0-9a-z]+")
SCAN_DIRS = ("gitops", "platform", "platform-charts", "workshop", "cluster-providers", "scripts")
SCAN_EXT = (".yaml", ".yml", ".tpl", ".json", ".k", ".py", ".sh")


def _activations():
    with open(REGISTRY) as f:
        reg = yaml.safe_load(f)
    vals = reg["crossplane"].get("valuesObject") or {}
    return (vals.get("provider") or {}).get("defaultActivations")


def _activated(name, acts):
    return any(fnmatch.fnmatchcase(name, a) for a in acts)


def _referenced_groups():
    groups = set()
    me = os.path.abspath(__file__)
    for d in SCAN_DIRS:
        for root, dirs, files in os.walk(os.path.join(REPO, d)):
            dirs[:] = [x for x in dirs if x not in ("node_modules", ".git", "build")]
            for fn in files:
                p = os.path.join(root, fn)
                if not fn.endswith(SCAN_EXT) or os.path.abspath(p) == me:
                    continue
                try:
                    with open(p, errors="ignore") as f:
                        groups.update(MR_GROUP.findall(f.read()))
                except OSError:
                    pass
    return groups


def test_default_activations_are_set_and_not_a_catch_all():
    acts = _activations()
    assert acts, "crossplane valuesObject.provider.defaultActivations must be set (chart default is ['*'])"
    assert "*" not in acts
    # A catch-all in disguise would also activate an arbitrary namespaced MR.
    assert not _activated("vpcs.ec2.aws.m.upbound.io", acts)


@pytest.mark.parametrize("name", [
    "roles.iam.aws.m.upbound.io",
    "clusters.eks.aws.m.upbound.io",
    "vpcs.ec2.aws.m.upbound.io",
    "workspaces.amp.aws.m.upbound.io",
    "memories.bedrockagentcore.aws.m.upbound.io",
])
def test_namespaced_aws_variants_are_not_activated(name):
    assert not _activated(name, _activations())


@pytest.mark.parametrize("name", [
    "roles.iam.aws.upbound.io",
    "podidentityassociations.eks.aws.upbound.io",
    "securitygrouprules.ec2.aws.upbound.io",
    "scrapers.amp.aws.upbound.io",
    "workspacesamlconfigurations.grafana.aws.upbound.io",
    "tables.dynamodb.aws.upbound.io",
    "instances.rds.aws.upbound.io",
    "buckets.s3.aws.upbound.io",
    "secrets.secretsmanager.aws.upbound.io",
    # Used by the agent platform (OAP) on the hub.
    "memories.bedrockagentcore.aws.upbound.io",
    "objects.kubernetes.crossplane.io",
])
def test_kinds_in_use_on_the_hub_stay_activated(name):
    assert _activated(name, _activations())


def test_every_group_referenced_in_the_repo_is_activated():
    groups = _referenced_groups()
    # Sanity: the scan must find the groups the platform is known to use.
    assert {"iam.aws.upbound.io", "eks.aws.upbound.io", "ec2.aws.upbound.io"} <= groups, groups
    acts = _activations()
    missing = sorted(g for g in groups if not _activated(f"anykind.{g}", acts))
    assert not missing, f"managed-resource groups used in the repo but not activated: {missing}"
