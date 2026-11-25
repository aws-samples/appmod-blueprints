"""Hermetic tests: the VPC reaper deletes leftover VPC Block Public Access exclusions.

The kro Vpc graph creates one exclusion per public subnet and deletes them from a
guard Pod. When the guard is skipped they leak, so clear_vpc_deps deletes, before the
subnets, every exclusion whose ResourceArn is the VPC or one of its subnets, whatever
its tags, and leaves other VPCs' exclusions and already-deleted ones alone.

No boto3, no network, no real sleeping.

Run:  python -m pytest workshop/scripts/tests/test_sweep_vpc_bpa_exclusions.py -q
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sweep.reapers import vpc as vpc_reaper  # noqa: E402

ARN = "arn:aws:ec2:us-west-2:123456789012"


def _ex(ex_id, resource, state="create-complete", tags=None):
    return {
        "ExclusionId": ex_id,
        "ResourceArn": f"{ARN}:{resource}",
        "State": state,
        "InternetGatewayExclusionMode": "allow-bidirectional",
        "Tags": tags or [],
    }


class _FakeEc2:
    def __init__(self, subnets, exclusions, fail_describe=False):
        self.subnets = subnets
        self.exclusions = exclusions
        self.fail_describe = fail_describe
        self.calls = []
        self.describe_kwargs = None

    def describe_subnets(self, Filters):
        vpc = Filters[0]["Values"][0]
        return {"Subnets": [{"SubnetId": s} for s in self.subnets.get(vpc, [])]}

    def describe_vpc_block_public_access_exclusions(self, **kwargs):
        self.describe_kwargs = kwargs
        if self.fail_describe:
            raise RuntimeError("AccessDenied")
        return {"VpcBlockPublicAccessExclusions": self.exclusions}

    def delete_vpc_block_public_access_exclusion(self, ExclusionId):
        self.calls.append(("delete_exclusion", ExclusionId))

    def delete_subnet(self, SubnetId):
        self.calls.append(("delete_subnet", SubnetId))

    def describe_network_interfaces(self, Filters):
        return {"NetworkInterfaces": []}

    def describe_nat_gateways(self, Filter):
        return {"NatGateways": []}

    def describe_internet_gateways(self, Filters):
        return {"InternetGateways": []}

    def describe_route_tables(self, Filters):
        return {"RouteTables": []}

    def describe_security_groups(self, Filters):
        return {"SecurityGroups": []}


def _ctx(ec2):
    ns = types.SimpleNamespace(ec2=ec2, _log_lines=[])
    ns.log = lambda m: ns._log_lines.append(m)
    ns.revoke_sg_rules = lambda sg: None
    ns.delete_vpc_sgs = lambda vpc_id: 0
    return ns


def _deleted(ec2):
    return [i for (op, i) in ec2.calls if op == "delete_exclusion"]


def test_deletes_subnet_and_vpc_exclusions_of_this_vpc_only():
    ec2 = _FakeEc2(
        subnets={"vpc-a": ["subnet-a1", "subnet-a2"], "vpc-b": ["subnet-b1"]},
        exclusions=[
            _ex("ex-a1", "subnet/subnet-a1"),
            _ex("ex-a2", "subnet/subnet-a2", state="update-complete"),
            _ex("ex-avpc", "vpc/vpc-a", state="create-in-progress"),
            _ex("ex-b1", "subnet/subnet-b1"),
            _ex("ex-bvpc", "vpc/vpc-b"),
            # Prefix of another id must not match: anchored on the full id.
            _ex("ex-a10", "subnet/subnet-a10"),
        ],
    )
    vpc_reaper.clear_vpc_deps(_ctx(ec2), "vpc-a")
    assert sorted(_deleted(ec2)) == ["ex-a1", "ex-a2", "ex-avpc"]
    # MaxResults is mandatory when ExclusionIds is absent.
    assert ec2.describe_kwargs == {"MaxResults": 1000}


def test_tag_agnostic_hand_made_exclusion_is_deleted():
    ec2 = _FakeEc2(
        subnets={"vpc-a": ["subnet-a1"]},
        exclusions=[_ex("ex-hand", "subnet/subnet-a1", tags=[{"Key": "Name", "Value": "by-hand"}])],
    )
    vpc_reaper.clear_vpc_deps(_ctx(ec2), "vpc-a")
    assert _deleted(ec2) == ["ex-hand"]


def test_already_deleting_or_deleted_exclusions_are_not_reissued():
    ec2 = _FakeEc2(
        subnets={"vpc-a": ["subnet-a1", "subnet-a2"]},
        exclusions=[
            _ex("ex-1", "subnet/subnet-a1", state="delete-complete"),
            _ex("ex-2", "subnet/subnet-a2", state="delete-in-progress"),
            _ex("ex-3", "vpc/vpc-a", state="disable-complete"),
        ],
    )
    vpc_reaper.clear_vpc_deps(_ctx(ec2), "vpc-a")
    assert _deleted(ec2) == []


def test_exclusions_deleted_before_subnets():
    ec2 = _FakeEc2(
        subnets={"vpc-a": ["subnet-a1"]},
        exclusions=[_ex("ex-a1", "subnet/subnet-a1")],
    )
    vpc_reaper.clear_vpc_deps(_ctx(ec2), "vpc-a")
    ops = [op for (op, _) in ec2.calls]
    assert ops.index("delete_exclusion") < ops.index("delete_subnet")


def test_describe_failure_is_logged_and_the_clear_goes_on():
    ec2 = _FakeEc2(subnets={"vpc-a": ["subnet-a1"]}, exclusions=[], fail_describe=True)
    ctx = _ctx(ec2)
    vpc_reaper.clear_vpc_deps(ctx, "vpc-a")
    assert any("VPC BPA exclusions for vpc-a: AccessDenied" in m for m in ctx._log_lines)
    # The rest of the dependency clear still ran.
    assert ("delete_subnet", "subnet-a1") in ec2.calls
