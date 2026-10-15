"""Hermetic tests: a stack's teardown sweep touches only its OWN account-wide resources.

AMP scrapers, the IDE VPC (its security groups) and Elastic IPs are account-wide, so
the sweep must identify them positively by this deployment's prefix. Two workshop
stacks share one account/region in the fixture below; each stack's teardown must
delete its own resources and leave the other stack's alone.

No boto3, no network, no real sleeping.

Run:  python -m pytest workshop/scripts/tests/test_sweep_prefix_scope.py -q
"""
import os
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sweep.context import SweepContext  # noqa: E402
from sweep.reapers import amp as amp_reaper  # noqa: E402
from sweep.reapers import eip as eip_reaper  # noqa: E402
from sweep.reapers import resweep as resweep_reaper  # noqa: E402
from sweep.reapers import verify as verify_reaper  # noqa: E402
from sweep.reapers import vpc as vpc_reaper  # noqa: E402


# ── Fixture ───────────────────────────────────────────────────────────────────
# Two workshop stacks in one account/region: stack 1 "peeks" (an older template: IDE
# VPC without the prefix tag, stack named peeks-workshop-main) and stack 2 "pvt" (the
# published template: IDE VPC tagged platform.gitops.io/prefix=pvt but still carrying
# the literal Name "peeks-workshop/IDE-VPC"). Each stack's teardown must touch only its
# own scrapers, IDE-VPC security groups and Elastic IPs.

PFX_TAG = "platform.gitops.io/prefix"


def _tags(**kv):
    return [{"Key": k, "Value": v} for k, v in kv.items()]


def _cfn(stack, **kv):
    return _tags(**{"aws:cloudformation:stack-name": stack, **kv})


class _Empty:
    """Empty AWS response: [] for any [key], the default for .get()."""

    def __getitem__(self, key):
        return []

    def get(self, key, default=None):
        return default


class _Pages:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, *a, **k):
        return iter(self._pages)


def _arn(cluster):
    return f"arn:aws:eks:us-west-2:111122223333:cluster/{cluster}"


ACCOUNT = {
    # name -> tags (pvt-team-a: an arbitrarily named spoke, owned by tag)
    "clusters": {
        "peeks-hub": {}, "peeks-spoke-dev": {}, "peeks-spoke-prod": {},
        "pvt-hub": {}, "pvt-spoke-dev": {}, "pvt-team-a": {PFX_TAG: "pvt"},
        "unrelated": {},
    },
    "scrapers": [
        {"scraperId": "s-peeks-hub", "source": {"eksConfiguration": {"clusterArn": _arn("peeks-hub")}}},
        {"scraperId": "s-peeks-dev", "source": {"eksConfiguration": {"clusterArn": _arn("peeks-spoke-dev")}}},
        {"scraperId": "s-peeks-prod", "source": {"eksConfiguration": {"clusterArn": _arn("peeks-spoke-prod")}}},
        {"scraperId": "s-pvt-hub", "source": {"eksConfiguration": {"clusterArn": _arn("pvt-hub")}}},
        {"scraperId": "s-pvt-dev", "source": {"eksConfiguration": {"clusterArn": _arn("pvt-spoke-dev")}}},
        {"scraperId": "s-pvt-team-a", "source": {"eksConfiguration": {"clusterArn": _arn("pvt-team-a")}}},
        {"scraperId": "s-unrelated", "source": {"eksConfiguration": {"clusterArn": _arn("unrelated")}}},
        {"scraperId": "s-no-eks-source", "source": {}},
    ],
    "vpcs": [
        {"VpcId": "vpc-stack1-ide", "Tags": _cfn("peeks-workshop-main", Name="peeks-workshop/IDE-VPC",
                                                 ResourcePrefix="peeks")},
        {"VpcId": "vpc-stack2-ide", "Tags": _cfn("pvt-workshop", Name="peeks-workshop/IDE-VPC",
                                                 ResourcePrefix="peeks", **{PFX_TAG: "pvt"})},
        {"VpcId": "vpc-other-cfn", "Tags": _cfn("network-workshop-prod", Name="shared-network")},
        {"VpcId": "vpc-peeks-spoke", "Tags": _tags(Name="peeks-spoke-dev-vpc", **{PFX_TAG: "peeks"})},
    ],
    "sgs": {
        # per VPC: one workshop-created SG and one CFN-owned SG (never swept, #1031)
        vid: [
            {"GroupId": f"sg-{vid}-hub", "GroupName": "eks-cluster-sg", "Tags": [],
             "IpPermissions": [{"IpProtocol": "-1"}], "IpPermissionsEgress": []},
            {"GroupId": f"sg-{vid}-ide", "GroupName": "ide", "Tags": _cfn("x"),
             "IpPermissions": [], "IpPermissionsEgress": []},
        ]
        for vid in ("vpc-stack1-ide", "vpc-stack2-ide", "vpc-other-cfn")
    },
    "addresses": [
        # stack 1's spoke NAT EIP, as the kro VPC RGD tags it (no ownership tag)
        {"AllocationId": "eip-peeks-spoke", "Tags": _tags(
            Name="peeks-spoke-dev-eip1", **{
                "eks:kubernetes-resource-name": "peeks-spoke-dev-eip1",
                "eks:eks-capability-arn": "arn:aws:eks:us-west-2:111122223333:capability/peeks-hub/ack/ack/x"})},
        # stack 2's own spoke NAT EIP and a Crossplane one (ownership tag)
        {"AllocationId": "eip-pvt-spoke", "Tags": _tags(Name="pvt-spoke-dev-eip1")},
        {"AllocationId": "eip-pvt-tagged", "Tags": _tags(**{PFX_TAG: "pvt"})},
        # the prefix only appears inside some other tag value: never ours
        {"AllocationId": "eip-substring", "Tags": _tags(Name="bastion", Owner="team-pvt-peeks")},
        # attached: never touched by anyone
        {"AllocationId": "eip-attached", "AssociationId": "a-1", "Tags": _tags(Name="pvt-spoke-prod-eip1")},
    ],
}


class _ScopeClient:
    """Fake boto3 client over ACCOUNT. Reads return the fixture; every other call is
    recorded in `calls` and returns an empty response."""

    def __init__(self, service, calls, account):
        self._s, self._calls, self._a = service, calls, account
        self.exceptions = types.SimpleNamespace(ResourceNotFoundException=KeyError)

    def get_paginator(self, op):
        if self._s == "eks" and op == "list_clusters":
            return _Pages([{"clusters": list(self._a["clusters"])}])
        return _Pages([])

    def describe_cluster(self, name):
        return {"cluster": {"tags": self._a["clusters"][name], "status": "ACTIVE"}}

    def list_scrapers(self, **k):
        return {"scrapers": self._a["scrapers"]}

    def list_workspaces(self, **k):
        return {"workspaces": []}

    def describe_vpcs(self, VpcIds=None, Filters=None):
        vpcs = self._a["vpcs"]
        if VpcIds:
            vpcs = [v for v in vpcs if v["VpcId"] in VpcIds]
        for f in Filters or []:
            key, vals = f["Name"].split(":", 1)[1], f["Values"]
            vpcs = [v for v in vpcs if {t["Key"]: t["Value"] for t in v["Tags"]}.get(key) in vals]
        return {"Vpcs": vpcs}

    def describe_security_groups(self, Filters=None, **k):
        vid = Filters[0]["Values"][0] if Filters and Filters[0]["Name"] == "vpc-id" else None
        return {"SecurityGroups": self._a["sgs"].get(vid, [])}

    def describe_addresses(self, **k):
        return {"Addresses": self._a["addresses"]}

    def __getattr__(self, name):
        def _call(*a, **k):
            if not name.startswith(("describe_", "list_", "get_")):
                self._calls.append((self._s, name, k))
            return _Empty()
        return _call


def _scope_ctx(prefix, account=ACCOUNT):
    calls = []
    with mock.patch("sweep.context.boto3.client",
                    side_effect=lambda service, **kw: _ScopeClient(service, calls, account)):
        ctx = SweepContext("us-west-2", prefix)
    return ctx, calls


def _targets(calls, method, key):
    return sorted(k[key] for _s, m, k in calls if m == method)


def test_amp_reap_deletes_only_this_stacks_scrapers():
    ctx, calls = _scope_ctx("pvt")
    amp_reaper.reap(ctx)
    # hub + legacy-named spoke + tag-discovered spoke; never stack 1's or unrelated ones
    assert _targets(calls, "delete_scraper", "scraperId") == ["s-pvt-dev", "s-pvt-hub", "s-pvt-team-a"]

    ctx, calls = _scope_ctx("peeks")
    amp_reaper.reap(ctx)
    assert _targets(calls, "delete_scraper", "scraperId") == ["s-peeks-dev", "s-peeks-hub", "s-peeks-prod"]


def test_amp_reap_empty_marker_when_only_other_stacks_scrapers():
    account = dict(ACCOUNT, scrapers=[s for s in ACCOUNT["scrapers"] if s["scraperId"].startswith("s-peeks")])
    ctx, calls = _scope_ctx("pvt", account)
    out = []
    ctx.log = out.append
    amp_reaper.reap(ctx)
    assert _targets(calls, "delete_scraper", "scraperId") == []
    assert "No AMP scrapers to delete" in out


def test_is_our_ide_vpc_scoped_to_prefix():
    ctx, _ = _scope_ctx("peeks")
    t = lambda tags: {x["Key"]: x["Value"] for x in tags}  # noqa: E731
    # stack names this deployment can have on a template without the prefix tag
    for stack in ("peeks-workshop", "peeks-workshop-team-stack", "peeks-workshop-main"):
        assert ctx.is_our_ide_vpc(t(_cfn(stack))), stack
    # the prefix tag decides when present, whatever the stack is called (TaskCat, renamed)
    assert ctx.is_our_ide_vpc(t(_cfn("tCaT-appmod-test-abc", **{PFX_TAG: "peeks"})))
    assert not ctx.is_our_ide_vpc(t(_cfn("peeks-workshop", **{PFX_TAG: "pvt"})))
    # names that merely contain "peeks" or "workshop" are other stacks
    for stack in ("pvt-workshop", "network-workshop-prod", "peeksworkshop", "my-peeks-workshop",
                  "tCaT-peeks-workshop-x"):
        assert not ctx.is_our_ide_vpc(t(_cfn(stack))), stack
    assert not ctx.is_our_ide_vpc(t(_tags(Name="peeks-workshop/IDE-VPC")))  # not CFN-owned

    ctx, _ = _scope_ctx("pvt")
    assert ctx.is_our_ide_vpc(t(_cfn("pvt-workshop", **{PFX_TAG: "pvt"})))
    assert ctx.is_our_ide_vpc(t(_cfn("pvt-workshop-team-stack")))
    assert not ctx.is_our_ide_vpc(t(_cfn("peeks-workshop-main", Name="peeks-workshop/IDE-VPC")))


def test_find_ide_vpc_two_stacks_each_finds_its_own():
    assert _scope_ctx("pvt")[0].find_ide_vpc() == "vpc-stack2-ide"
    assert _scope_ctx("peeks")[0].find_ide_vpc() == "vpc-stack1-ide"


def _one_stack(stack, **extra):
    vpc = {"VpcId": "vpc-only-ide", "Tags": _cfn(stack, Name="peeks-workshop/IDE-VPC", **extra)}
    return dict(ACCOUNT, vpcs=[vpc, ACCOUNT["vpcs"][2], ACCOUNT["vpcs"][3]],
                sgs=dict(ACCOUNT["sgs"], **{"vpc-only-ide": ACCOUNT["sgs"]["vpc-stack1-ide"]}))


def test_ide_sg_reapers_single_stack_self_paced_and_workshop_studio():
    # The hub is already gone (ctx.hub_vpc_id unset): §15 and §16e must still find the
    # stack's own IDE VPC by stack name, and only delete the non-CFN SGs in it.
    for stack in ("peeks-workshop", "peeks-workshop-team-stack"):
        for reap in (vpc_reaper.reap_ide_sgs, resweep_reaper.run):
            ctx, calls = _scope_ctx("peeks", _one_stack(stack))
            reap(ctx)
            assert _targets(calls, "delete_security_group", "GroupId") == ["sg-vpc-stack1-ide-hub"], (stack, reap)


def test_ide_sg_reapers_never_touch_another_stacks_vpc():
    # Today's account: only stack 1 exists (its IDE VPC and a spoke VPC). A second
    # stack's (pvt) teardown must not revoke or delete anything in stack 1's IDE VPC,
    # where stack 1's hub cluster SG lives.
    only_stack1 = dict(ACCOUNT, vpcs=[ACCOUNT["vpcs"][0], ACCOUNT["vpcs"][3]])
    for reap in (vpc_reaper.reap_ide_sgs, resweep_reaper.run):
        ctx, calls = _scope_ctx("pvt", only_stack1)
        reap(ctx)
        touched = [m for _s, m, _k in calls if "security_group" in m]
        assert touched == [], (reap, touched)
    # Both stacks present: each stack's teardown clears only its own IDE VPC.
    for prefix, own in (("pvt", "vpc-stack2-ide"), ("peeks", "vpc-stack1-ide")):
        for reap in (vpc_reaper.reap_ide_sgs, resweep_reaper.run):
            ctx, calls = _scope_ctx(prefix)
            reap(ctx)
            groups = {k["GroupId"] for _s, m, k in calls if "security_group" in m}
            assert groups == {f"sg-{own}-hub"}, (prefix, reap, groups)


def test_vpc_is_ours_prefix_tag_is_authoritative():
    # Stack 2's IDE VPC keeps the literal Name "peeks-workshop/IDE-VPC": stack 1's
    # GuardDuty reapers (§13b/§15b) must not claim it through the Name prefix.
    ctx, _ = _scope_ctx("peeks")
    assert not ctx.vpc_is_ours("vpc-stack2-ide")
    assert ctx.vpc_is_ours("vpc-stack1-ide")
    assert ctx.vpc_is_ours("vpc-peeks-spoke")
    assert not ctx.vpc_is_ours("vpc-other-cfn")
    ctx, _ = _scope_ctx("pvt")
    assert ctx.vpc_is_ours("vpc-stack2-ide")
    assert not ctx.vpc_is_ours("vpc-stack1-ide")
    assert not ctx.vpc_is_ours("vpc-peeks-spoke")


def test_eip_reapers_release_only_this_stacks_addresses():
    ctx, calls = _scope_ctx("pvt")
    eip_reaper.reap(ctx)
    assert _targets(calls, "release_address", "AllocationId") == ["eip-pvt-spoke", "eip-pvt-tagged"]

    ctx, calls = _scope_ctx("peeks")
    eip_reaper.reap(ctx)
    assert _targets(calls, "release_address", "AllocationId") == ["eip-peeks-spoke"]

    # §17a re-release and the §17c residue scan use the same predicate.
    ctx, calls = _scope_ctx("pvt")
    out = []
    ctx.log = out.append
    residue = verify_reaper.run(ctx)
    assert _targets(calls, "release_address", "AllocationId") == ["eip-pvt-spoke", "eip-pvt-tagged"]
    assert not any("eip-substring" in r or "bastion" in r for r in residue)
