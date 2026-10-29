"""Unit tests for scripts/sweep_lib.py and the kind-kro-ack destroy wiring that uses it:
the teardown removes the hub's own VPC, the <prefix>-devlake-* RDS and the EKS log
groups of every cluster it removed, and never touches what a live (e.g. retained)
cluster or another deployment still uses.

The AWS clients are in-memory fakes holding a mutable account state: deletes change it,
so ordering (NAT gone before EIP release, RDS gone before its subnet group) is
observable. No AWS, no network, no sleeping.

Run:  python -m pytest workshop/scripts/tests/test_sweep_orphans.py -q
"""
import importlib.util
import os
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import sweep_lib as sl  # noqa: E402

TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
NOSLEEP = lambda *_: None  # noqa: E731


class AwsError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code, "Message": "principal arn:aws:iam::111122223333:x"}}
        super().__init__(f"An error occurred ({code}) when calling the op: principal ...")


def tags(**kv):
    return [{"Key": k.replace("__", "/").replace("_", "."), "Value": v} for k, v in kv.items()]


def T(d):
    return [{"Key": k, "Value": v} for k, v in d.items()]


# ------------------------------------------------------------------ fakes

class FakeEc2:
    def __init__(self):
        self.vpcs, self.nats, self.endpoints, self.igws = {}, {}, {}, {}
        self.subnets, self.rts, self.sgs, self.enis, self.eips = {}, {}, {}, {}, set()
        self.calls = []
        self.nat_delete_polls = 2  # a NAT stays "deleting" for two polls

    def add_vpc(self, vpc_id, vtags, endpoint=True):
        self.vpcs[vpc_id] = {"VpcId": vpc_id, "Tags": T(vtags)}
        self.nats[f"{vpc_id}-nat"] = {"NatGatewayId": f"{vpc_id}-nat", "VpcId": vpc_id, "State": "available",
                                      "NatGatewayAddresses": [{"AllocationId": f"{vpc_id}-eip"}]}
        self.eips.add(f"{vpc_id}-eip")
        if endpoint:
            self.endpoints[f"{vpc_id}-vpce"] = {"VpcEndpointId": f"{vpc_id}-vpce", "VpcId": vpc_id,
                                                "State": "available"}
        self.igws[f"{vpc_id}-igw"] = {"InternetGatewayId": f"{vpc_id}-igw", "Attachments": [{"VpcId": vpc_id}]}
        for s in ("a", "b"):
            self.subnets[f"{vpc_id}-sn-{s}"] = {"SubnetId": f"{vpc_id}-sn-{s}", "VpcId": vpc_id}
        self.rts[f"{vpc_id}-rt-main"] = {"RouteTableId": f"{vpc_id}-rt-main", "VpcId": vpc_id,
                                         "Associations": [{"Main": True}]}
        self.rts[f"{vpc_id}-rt-priv"] = {"RouteTableId": f"{vpc_id}-rt-priv", "VpcId": vpc_id, "Associations": [
            {"Main": False, "RouteTableAssociationId": f"{vpc_id}-assoc"}]}
        self.sgs[f"{vpc_id}-sg-default"] = {"GroupId": f"{vpc_id}-sg-default", "GroupName": "default", "VpcId": vpc_id}
        self.sgs[f"{vpc_id}-sg-x"] = {"GroupId": f"{vpc_id}-sg-x", "GroupName": "x", "VpcId": vpc_id,
                                      "IpPermissions": [{"IpProtocol": "-1"}]}

    # -- reads
    def _vpc_filter(self, items, filters):
        out = []
        for o in items:
            ok = True
            for f in filters or []:
                n, vals = f["Name"], f["Values"]
                if n.startswith("tag:"):
                    ok &= {t["Key"]: t["Value"] for t in o.get("Tags", [])}.get(n[4:]) in vals
                elif n == "vpc-id":
                    ok &= o.get("VpcId") in vals
                elif n == "attachment.vpc-id":
                    ok &= any(a["VpcId"] in vals for a in o.get("Attachments", []))
                elif n == "state":
                    ok &= o.get("State") in vals
            if ok:
                out.append(o)
        return out

    def describe_vpcs(self, Filters=None, VpcIds=None):
        items = list(self.vpcs.values())
        if VpcIds:
            items = [v for v in items if v["VpcId"] in VpcIds]
            if not items:
                raise AwsError("InvalidVpcID.NotFound")
        return {"Vpcs": self._vpc_filter(items, Filters)}

    def describe_nat_gateways(self, Filters):
        for n in self.nats.values():  # time passes on each poll
            if n["State"] == "deleting":
                n["_polls"] = n.get("_polls", 0) + 1
                if n["_polls"] > self.nat_delete_polls:
                    n["State"] = "deleted"
        return {"NatGateways": self._vpc_filter(self.nats.values(), Filters)}

    def describe_vpc_endpoints(self, Filters):
        return {"VpcEndpoints": self._vpc_filter(self.endpoints.values(), Filters)}

    def describe_internet_gateways(self, Filters):
        return {"InternetGateways": self._vpc_filter(self.igws.values(), Filters)}

    def describe_subnets(self, Filters):
        return {"Subnets": self._vpc_filter(self.subnets.values(), Filters)}

    def describe_route_tables(self, Filters):
        return {"RouteTables": self._vpc_filter(self.rts.values(), Filters)}

    def describe_security_groups(self, Filters):
        return {"SecurityGroups": self._vpc_filter(self.sgs.values(), Filters)}

    def describe_network_interfaces(self, Filters):
        return {"NetworkInterfaces": self._vpc_filter(self.enis.values(), Filters)}

    # -- writes (recorded)
    def _rec(self, op, **kw):
        self.calls.append((op, kw))

    def delete_nat_gateway(self, NatGatewayId):
        self._rec("delete_nat_gateway", id=NatGatewayId)
        self.nats[NatGatewayId]["State"] = "deleting"

    def delete_vpc_endpoints(self, VpcEndpointIds):
        self._rec("delete_vpc_endpoints", ids=VpcEndpointIds)
        for i in VpcEndpointIds:
            self.endpoints.pop(i)

    def release_address(self, AllocationId):
        self._rec("release_address", id=AllocationId)
        if any(n["State"] in ("available", "deleting") and
               any(a["AllocationId"] == AllocationId for a in n["NatGatewayAddresses"])
               for n in self.nats.values()):
            raise AwsError("InvalidIPAddress.InUse")
        self.eips.discard(AllocationId)

    def detach_internet_gateway(self, InternetGatewayId, VpcId):
        self._rec("detach_internet_gateway", id=InternetGatewayId)

    def delete_internet_gateway(self, InternetGatewayId):
        self._rec("delete_internet_gateway", id=InternetGatewayId)
        self.igws.pop(InternetGatewayId)

    def delete_subnet(self, SubnetId):
        self._rec("delete_subnet", id=SubnetId)
        vpc = self.subnets[SubnetId]["VpcId"]
        if any(n["VpcId"] == vpc and n["State"] in ("available", "deleting") for n in self.nats.values()):
            raise AwsError("DependencyViolation")
        self.subnets.pop(SubnetId)

    def disassociate_route_table(self, AssociationId):
        self._rec("disassociate_route_table", id=AssociationId)

    def delete_route_table(self, RouteTableId):
        self._rec("delete_route_table", id=RouteTableId)
        self.rts.pop(RouteTableId)

    def revoke_security_group_ingress(self, GroupId, IpPermissions):
        self._rec("revoke_security_group_ingress", id=GroupId)

    def revoke_security_group_egress(self, GroupId, IpPermissions):
        self._rec("revoke_security_group_egress", id=GroupId)

    def delete_security_group(self, GroupId):
        self._rec("delete_security_group", id=GroupId)
        self.sgs.pop(GroupId)

    def delete_network_interface(self, NetworkInterfaceId):
        self._rec("delete_network_interface", id=NetworkInterfaceId)
        self.enis.pop(NetworkInterfaceId)

    def delete_vpc(self, VpcId):
        self._rec("delete_vpc", id=VpcId)
        left = [s for s in self.subnets.values() if s["VpcId"] == VpcId]
        if left:
            raise AwsError("DependencyViolation")
        self.vpcs.pop(VpcId)

    def writes_on(self, vpc_id):
        return [c for c in self.calls if vpc_id in str(c[1])]


class FakeEks:
    def __init__(self, clusters):
        """clusters: name -> dict(status, vpc, roleArn, access=[arns], pia=[role arns], caps=[role arns])"""
        self.c = clusters

    def list_clusters(self, **_):
        return {"clusters": list(self.c)}

    def describe_cluster(self, name):
        c = self.c[name]
        return {"cluster": {"status": c["status"], "resourcesVpcConfig": {"vpcId": c.get("vpc", "")},
                            "roleArn": c.get("roleArn", ""), "tags": {}}}

    def list_access_entries(self, clusterName, **_):
        return {"accessEntries": self.c[clusterName].get("access", [])}

    def list_pod_identity_associations(self, clusterName, **_):
        return {"associations": [{"associationId": str(i)} for i, _ in
                                 enumerate(self.c[clusterName].get("pia", []))]}

    def describe_pod_identity_association(self, clusterName, associationId):
        return {"association": {"roleArn": self.c[clusterName]["pia"][int(associationId)]}}

    def list_capabilities(self, clusterName, **_):
        return {"capabilities": [{"capabilityName": str(i)} for i, _ in
                                 enumerate(self.c[clusterName].get("caps", []))]}

    def describe_capability(self, clusterName, capabilityName):
        return {"capability": {"roleArn": self.c[clusterName]["caps"][int(capabilityName)]}}


class FakeRds:
    def __init__(self, clusters=(), instances=(), subnet_groups=(), delete_polls=2):
        self.clusters = {c["DBClusterIdentifier"]: dict(c) for c in clusters}
        self.instances = {i["DBInstanceIdentifier"]: dict(i) for i in instances}
        self.subnet_groups = set(subnet_groups)
        self.calls, self.polls, self.delete_polls = [], 0, delete_polls

    def _tick(self):
        self.polls += 1
        if self.polls > self.delete_polls:
            for d in (self.clusters, self.instances):
                for k in [k for k, v in d.items() if v.get("Status", v.get("DBInstanceStatus")) == "deleting"]:
                    d.pop(k)

    def describe_db_clusters(self, **_):
        self._tick()
        return {"DBClusters": list(self.clusters.values())}

    def describe_db_instances(self, **_):
        return {"DBInstances": list(self.instances.values())}

    def describe_db_subnet_groups(self, **_):
        return {"DBSubnetGroups": [{"DBSubnetGroupName": g} for g in sorted(self.subnet_groups)]}

    def delete_db_instance(self, **kw):
        self.calls.append(("delete_db_instance", kw))
        self.instances[kw["DBInstanceIdentifier"]]["DBInstanceStatus"] = "deleting"

    def delete_db_cluster(self, **kw):
        self.calls.append(("delete_db_cluster", kw))
        self.clusters[kw["DBClusterIdentifier"]]["Status"] = "deleting"

    def delete_db_subnet_group(self, DBSubnetGroupName):
        self.calls.append(("delete_db_subnet_group", DBSubnetGroupName))
        owner = DBSubnetGroupName.split("-devlake-")[0] + "-devlake-"
        if any(k.startswith(owner) for k in self.clusters):
            raise AwsError("InvalidDBSubnetGroupStateFault")
        self.subnet_groups.discard(DBSubnetGroupName)


class FakeLogs:
    def __init__(self, groups):
        self.groups, self.calls = list(groups), []

    def describe_log_groups(self, logGroupNamePrefix, **_):
        return {"logGroups": [{"logGroupName": g} for g in self.groups if g.startswith(logGroupNamePrefix)]}

    def delete_log_group(self, logGroupName):
        self.calls.append(logGroupName)
        self.groups.remove(logGroupName)


def hub_tags(prefix, hub, **extra):
    return {"Name": f"{hub}-vpc", "platform.gitops.io/prefix": prefix, "platform.gitops.io/cluster": hub,
            "services.k8s.aws/namespace": hub, **extra}


def spoke_tags(prefix, cluster):
    return {"Name": f"{cluster}-vpc", "eks:kubernetes-resource-name": f"{cluster}-vpc",
            "platform.gitops.io/prefix": prefix, "platform.gitops.io/cluster": cluster}


# ------------------------------------------------------------------ the two-hub account
# Mirrors the account the gaps were found on: hubs A and B (same 10.0/16 layout), each
# with a dev spoke, and a spoke "prod" (no prefix in its name) owned by hub A with
# deletionPolicy=retain, whose access entries hold hub A's management and Argo CD roles.

ACCT = "arn:aws:iam::111122223333:role/"


def account():
    ec2 = FakeEc2()
    ec2.add_vpc("vpc-a-hub", hub_tags("ha", "ha-hub"))
    ec2.add_vpc("vpc-a-dev", spoke_tags("ha", "ha-dev"))
    ec2.add_vpc("vpc-prod", spoke_tags("ha", "prod"))
    ec2.add_vpc("vpc-b-hub", hub_tags("hb", "hb-hub"))
    ec2.add_vpc("vpc-b-dev", spoke_tags("hb", "hb-dev"))
    clusters = {
        "ha-hub": {"status": "ACTIVE", "vpc": "vpc-a-hub", "roleArn": ACCT + "ha-hub-cluster-role"},
        "ha-dev": {"status": "ACTIVE", "vpc": "vpc-a-dev"},
        "prod": {"status": "ACTIVE", "vpc": "vpc-prod", "roleArn": ACCT + "prod-cluster-role",
                 "access": [ACCT + "ha-cluster-mgmt-eks", ACCT + "ha-hub-argocd-capability-role",
                            ACCT + "hb-hub-argocd-capability-role", "arn:aws:iam::111122223333:user/ops"],
                 "pia": [ACCT + "prod-ebs-csi"], "caps": [ACCT + "prod-ack-capability-role"]},
        "hb-hub": {"status": "ACTIVE", "vpc": "vpc-b-hub"},
        "hb-dev": {"status": "ACTIVE", "vpc": "vpc-b-dev"},
    }
    inv_a = {"hub_vpc_id": "vpc-a-hub", "clusters": [{"name": "ha-dev", "deletionPolicy": "delete"},
                                                     {"name": "prod", "deletionPolicy": "retain"}]}
    return ec2, clusters, inv_a


def gone(clusters, *names):
    out = {k: v for k, v in clusters.items() if k not in names}
    return out


# ------------------------------------------------------------------ gap 1: hub VPC

def test_hub_vpc_is_selected_once_the_hub_cluster_is_gone():
    ec2, clusters, inv = account()
    sel, _ = sl.select_hub_vpc(ec2, "ha", "ha-hub", gone(clusters, "ha-hub", "ha-dev"), inv)
    assert sel == ["vpc-a-hub"]


def test_hub_vpc_is_found_by_tags_without_an_inventory():
    ec2, clusters, _ = account()
    sel, _ = sl.select_hub_vpc(ec2, "ha", "ha-hub", gone(clusters, "ha-hub"), None)
    assert sel == ["vpc-a-hub"]


def test_hub_vpc_is_kept_while_the_hub_cluster_is_live():
    ec2, clusters, inv = account()
    sel, skipped = sl.select_hub_vpc(ec2, "ha", "ha-hub", clusters, inv)
    assert sel == [] and "live EKS cluster(s) ha-hub" in skipped[0][1]


def test_hub_vpc_is_kept_while_the_hub_is_still_deleting_is_not_live():
    ec2, clusters, inv = account()
    clusters = dict(clusters, **{"ha-hub": dict(clusters["ha-hub"], status="DELETING")})
    sel, _ = sl.select_hub_vpc(ec2, "ha", "ha-hub", clusters, inv)
    assert sel == ["vpc-a-hub"]  # DELETING is not live; clean_vpc then waits on its ENIs


def test_workshop_hub_in_the_cloudformation_vpc_is_never_selected():
    ec2 = FakeEc2()
    ec2.add_vpc("vpc-ide", {"platform.gitops.io/prefix": "peeks", "ResourceType": "ideHubVPC",
                            "aws:cloudformation:stack-name": "peeks-workshop"})
    inv = {"hub_vpc_id": "vpc-ide", "clusters": []}
    sel, skipped = sl.select_hub_vpc(ec2, "peeks", "peeks-hub", {}, inv)
    assert sel == [] and "CloudFormation" in skipped[0][1]


def test_recorded_hub_vpc_of_another_prefix_or_untagged_is_not_swept():
    ec2, clusters, _ = account()
    ec2.add_vpc("vpc-untagged", {"Name": "something"})
    for hint, want in (("vpc-b-hub", "prefix tag is 'hb'"), ("vpc-untagged", "not provably ours")):
        sel, skipped = sl.select_hub_vpc(ec2, "ha", "ha-hub", {}, {"hub_vpc_id": hint})
        assert hint not in sel and any(v == hint and want in r for v, r in skipped), skipped


def test_destroying_one_hub_never_selects_the_other_hub():
    ec2, clusters, inv = account()
    sel, _ = sl.select_hub_vpc(ec2, "ha", "ha-hub", gone(clusters, "ha-hub", "hb-hub"), inv)
    assert sel == ["vpc-a-hub"]


def test_clean_vpc_deletes_everything_in_dependency_order():
    ec2, _, _ = account()
    assert sl.clean_vpc(ec2, "vpc-a-hub", sleep=NOSLEEP)
    ops = [c[0] for c in ec2.writes_on("vpc-a-hub")]
    assert "vpc-a-hub" not in ec2.vpcs
    assert "vpc-a-hub-eip" not in ec2.eips, "NAT EIP not released"
    assert not [e for e in ec2.endpoints if e.startswith("vpc-a-hub")], "endpoint left"
    # The EIP is released and the subnets deleted only after the NAT gateway is gone.
    assert ops.index("delete_nat_gateway") < ops.index("release_address") < ops.index("delete_vpc")
    assert "delete_vpc_endpoints" in ops and "delete_internet_gateway" in ops
    assert "vpc-a-hub-sg-default" in ec2.sgs, "default SG must be left to delete_vpc"
    assert not [c for c in ec2.calls if "vpc-a-hub" not in str(c[1])], "touched another VPC"


def test_clean_vpc_disassociates_route_tables_before_deleting_subnets():
    # Deleting a subnet drops its association: disassociating afterwards only
    # fails with InvalidAssociationID.NotFound (seen on a real teardown).
    ec2, _, _ = account()
    assert sl.clean_vpc(ec2, "vpc-a-hub", sleep=NOSLEEP)
    ops = [c[0] for c in ec2.writes_on("vpc-a-hub")]
    assert ops.index("disassociate_route_table") < ops.index("delete_subnet") < ops.index("delete_route_table")


def test_clean_vpc_waits_for_detached_enis_and_deletes_them():
    ec2, _, _ = account()
    ec2.enis["eni-old"] = {"NetworkInterfaceId": "eni-old", "VpcId": "vpc-a-hub", "Status": "available",
                           "InterfaceType": "interface", "Description": "Amazon EKS ha-hub"}
    assert sl.clean_vpc(ec2, "vpc-a-hub", sleep=NOSLEEP)
    assert ("delete_network_interface", {"id": "eni-old"}) in ec2.calls


def test_dry_run_writes_nothing_and_lists_the_plan(capsys):
    ec2, clusters, inv = account()
    sel, skipped = sl.select_hub_vpc(ec2, "ha", "ha-hub", clusters, inv, assume_deleted=["ha-hub"])
    assert sl.run_vpc_sweep(ec2, "hub", sel, skipped, dry_run=True) == 0
    out = capsys.readouterr().out
    assert ec2.calls == []
    assert "[dry-run] would delete hub VPC vpc-a-hub: 1 NAT, 1 NAT EIP, 1 endpoint, 1 IGW, 2 subnet" in out


# ------------------------------------------------------------------ gap 4: spoke sweep safety

def test_retained_live_spoke_vpc_is_never_swept_with_its_prefix():
    """Destroying hub A: prod-vpc carries prefix A, but prod is ACTIVE (retain)."""
    ec2, clusters, inv = account()
    after = gone(clusters, "ha-hub", "ha-dev")
    sel, skipped = sl.select_spoke_vpcs(ec2, "ha", "ha-hub", after, inv)
    assert sel == ["vpc-a-dev"]
    reasons = dict(skipped)
    assert "live EKS cluster(s) prod" in reasons["vpc-prod"]
    assert "hub VPC" in reasons["vpc-a-hub"]


def test_retained_spoke_vpc_is_kept_even_when_its_cluster_is_not_listed():
    ec2, clusters, inv = account()
    after = gone(clusters, "ha-hub", "ha-dev", "prod")  # e.g. EKS API page missed it
    sel, skipped = sl.select_spoke_vpcs(ec2, "ha", "ha-hub", after, inv)
    assert "vpc-prod" not in sel and "deletionPolicy=retain" in dict(skipped)["vpc-prod"]


def test_spoke_vpc_with_a_live_cluster_is_never_swept_without_inventory():
    ec2, clusters, _ = account()
    sel, _ = sl.select_spoke_vpcs(ec2, "ha", "ha-hub", clusters, None)
    assert sel == []


def test_other_prefix_and_nested_prefix_are_never_swept():
    ec2, clusters, _ = account()
    ec2.add_vpc("vpc-nested", spoke_tags("ha-x", "ha-x-dev"))
    # a legacy-named VPC of prefix "ha" that another deployment re-tagged as its own
    ec2.add_vpc("vpc-legacy-foreign", {"eks:kubernetes-resource-name": "ha-spoke-dev-vpc",
                                       "platform.gitops.io/prefix": "zz"})
    sel, skipped = sl.select_spoke_vpcs(ec2, "ha", "ha-hub", {}, None)
    assert "vpc-nested" not in sel and "vpc-b-dev" not in sel
    assert "prefix tag is 'zz'" in dict(skipped)["vpc-legacy-foreign"]


def test_spoke_sweep_of_hub_b_does_not_touch_hub_a():
    ec2, clusters, _ = account()
    after = gone(clusters, "hb-hub", "hb-dev")
    sel, _ = sl.select_spoke_vpcs(ec2, "hb", "hb-hub", after, None)
    assert sel == ["vpc-b-dev"]


# ------------------------------------------------------------------ gap 4: IAM guard

def test_roles_referenced_by_a_live_cluster_are_protected():
    _, clusters, _ = account()
    after = gone(clusters, "ha-hub", "ha-dev")
    roles = sl.protected_roles(FakeEks(after), after)
    assert {"ha-cluster-mgmt-eks", "ha-hub-argocd-capability-role", "prod-cluster-role",
            "prod-ebs-csi", "prod-ack-capability-role"} <= roles
    assert "ops" not in roles, "an IAM user principal is not a role"
    assert "ha-hub-cluster-role" not in roles, "the deleted hub's role is sweepable"


def test_deleting_or_assumed_deleted_clusters_do_not_protect():
    _, clusters, _ = account()
    c = dict(clusters, prod=dict(clusters["prod"], status="DELETING"))
    assert "ha-cluster-mgmt-eks" not in sl.protected_roles(FakeEks(c), c)
    assert "ha-cluster-mgmt-eks" not in sl.protected_roles(FakeEks(clusters), clusters,
                                                          assume_deleted=["prod"])


def test_iam_guard_cli_fails_closed(capsys):
    spec = importlib.util.spec_from_file_location("guard", os.path.join(REPO, "scripts", "sweep-iam-guard.py"))
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    class Broken:
        def list_clusters(self, **_):
            raise AwsError("AccessDeniedException")
    assert guard.main(["us-west-2"], eks=Broken()) == 1


# ------------------------------------------------------------------ gap 2: RDS

def rds_account():
    return FakeRds(
        clusters=[{"DBClusterIdentifier": "ha-devlake-mysql-cluster", "Status": "available"},
                  {"DBClusterIdentifier": "hb-devlake-mysql-cluster", "Status": "available"},
                  {"DBClusterIdentifier": "ha-x-devlake-mysql-cluster", "Status": "available"},
                  {"DBClusterIdentifier": "devlake-mysql-db-legacy", "Status": "available"}],
        instances=[{"DBInstanceIdentifier": "ha-devlake-mysql-instance", "DBClusterIdentifier": "ha-devlake-mysql-cluster",
                    "DBInstanceStatus": "available"},
                   {"DBInstanceIdentifier": "hb-devlake-mysql-instance", "DBClusterIdentifier": "hb-devlake-mysql-cluster",
                    "DBInstanceStatus": "available"},
                   {"DBInstanceIdentifier": "devlake-mysql-db-abc", "DBInstanceStatus": "available"}],
        subnet_groups=["ha-devlake-mysql-subnet-group", "hb-devlake-mysql-subnet-group"])


def test_rds_sweep_deletes_the_prefix_devlake_aurora_and_legacy_instances():
    rds = rds_account()
    sl.sweep_rds(rds, "ha", sleep=NOSLEEP)
    deleted = [(op, kw.get("DBClusterIdentifier") or kw.get("DBInstanceIdentifier") if isinstance(kw, dict) else kw)
               for op, kw in rds.calls]
    assert ("delete_db_cluster", "ha-devlake-mysql-cluster") in deleted
    assert ("delete_db_instance", "ha-devlake-mysql-instance") in deleted
    assert ("delete_db_instance", "devlake-mysql-db-abc") in deleted, "legacy path unchanged"
    assert ("delete_db_subnet_group", "ha-devlake-mysql-subnet-group") in deleted
    assert "ha-devlake-mysql-subnet-group" not in rds.subnet_groups, "subnet group deleted after the wait"
    names = " ".join(str(c) for c in rds.calls)
    assert "hb-devlake" not in names and "ha-x-devlake" not in names, "another prefix touched"
    assert "devlake-mysql-db-legacy" not in names, "legacy instance-less cluster: unchanged (not swept)"
    for op, kw in rds.calls:
        if op in ("delete_db_cluster", "delete_db_instance"):
            assert kw["SkipFinalSnapshot"] is True


def test_rds_deletion_protection_is_respected():
    rds = FakeRds(clusters=[{"DBClusterIdentifier": "ha-devlake-c", "Status": "available", "DeletionProtection": True}])
    sl.sweep_rds(rds, "ha", sleep=NOSLEEP)
    assert not [c for c in rds.calls if c[0] == "delete_db_cluster"]


def test_rds_dry_run_writes_nothing(capsys):
    rds = rds_account()
    sl.sweep_rds(rds, "ha", dry_run=True, sleep=NOSLEEP)
    assert rds.calls == []
    assert "[dry-run] would delete RDS cluster ha-devlake-mysql-cluster" in capsys.readouterr().out


# ------------------------------------------------------------------ gap 3: log groups

GROUPS = ["/aws/eks/ha-hub/cluster", "/aws/eks/ha-hub/capability/kro", "/aws/eks/ha-dev/cluster",
          "/aws/eks/prod/cluster", "/aws/eks/hb-hub/cluster", "/aws/eks/hb-dev/cluster",
          "/aws/eks/ha-spoke-dev/cluster", "/aws/eks/teamx/cluster", "/aws/eks/oldspoke/cluster"]


def test_log_groups_of_removed_clusters_are_selected_any_spoke_name():
    _, clusters, inv = account()
    inv["clusters"].append({"name": "oldspoke", "deletionPolicy": "delete"})
    after = gone(clusters, "ha-hub", "ha-dev")
    sel, skipped = sl.select_log_groups(FakeLogs(GROUPS), "ha", "ha-hub", after, inv)
    assert sel == ["/aws/eks/ha-dev/cluster", "/aws/eks/ha-hub/capability/kro", "/aws/eks/ha-hub/cluster",
                   "/aws/eks/ha-spoke-dev/cluster", "/aws/eks/oldspoke/cluster"]
    assert "/aws/eks/prod/cluster" not in sel, "retained spoke keeps its logs"
    assert "/aws/eks/hb-hub/cluster" not in sel and "/aws/eks/teamx/cluster" not in sel


def test_log_groups_of_live_clusters_are_kept():
    _, clusters, inv = account()
    sel, skipped = sl.select_log_groups(FakeLogs(GROUPS), "ha", "ha-hub", clusters, inv)
    assert "/aws/eks/ha-hub/cluster" not in sel and "/aws/eks/ha-dev/cluster" not in sel
    assert "still ACTIVE" in dict(skipped)["/aws/eks/ha-dev/cluster"]


def test_log_group_sweep_deletes_and_dry_run_does_not():
    _, clusters, inv = account()
    logs = FakeLogs(GROUPS)
    sel, sk = sl.select_log_groups(logs, "ha", "ha-hub", gone(clusters, "ha-hub", "ha-dev"), inv)
    sl.sweep_log_groups(logs, sel, sk, dry_run=True)
    assert logs.calls == []
    sl.sweep_log_groups(logs, sel, sk)
    assert logs.calls == sel and "/aws/eks/hb-hub/cluster" in logs.groups


# ------------------------------------------------------------------ misc

def test_retained_prefix_named_spoke_keeps_its_log_groups():
    logs = FakeLogs(["/aws/eks/ha-staging/cluster"])
    inv = {"clusters": [{"name": "ha-staging", "deletionPolicy": "retain"}]}
    sel, skipped = sl.select_log_groups(logs, "ha", "ha-hub", {}, inv)
    assert sel == [] and "deletionPolicy=retain" in dict(skipped)["/aws/eks/ha-staging/cluster"]


def test_assume_deleted_requires_dry_run():
    with pytest.raises(SystemExit):
        sl.parse_common(["p", "r", "--assume-deleted", "x"], "")
    _, o = sl.parse_common(["p", "r", "--dry-run", "--assume-deleted", "x"], "")
    assert o["assume_deleted"] == ["x"] and o["dry_run"]


def test_error_lines_carry_the_code_only(capsys):
    def boom():
        raise AwsError("AccessDeniedException")
    assert sl._try(boom, "thing t1") is False
    out = capsys.readouterr().out
    assert "(AccessDeniedException)" in out and "arn:aws" not in out


def test_inventory_missing_or_corrupt_falls_back(tmp_path):
    p = tmp_path / "inv.json"
    p.write_text("{not json")
    assert sl.load_inventory(str(p)) == {"hub_vpc_id": "", "clusters": []}
    assert sl.load_inventory(str(tmp_path / "absent.json"))["clusters"] == []


def test_destroy_wiring():
    """Inventory recorded before kind is deleted; RDS before the hub VPC; hub VPC after
    the spoke VPCs; both role sweeps guarded."""
    text = open(TASKFILE).read()
    destroy = text[text.index("\n  destroy:\n"):text.index("# ---- from kind-crossplane ----")]
    assert destroy.index("destroy-inventory.json") < destroy.index("kind delete cluster --name")
    i_rds, i_spoke, i_hub = (destroy.index(f'scripts/{s}"') for s in ("sweep-rds.py", "sweep-spoke-vpcs.py", "sweep-hub-vpc.py"))
    assert i_rds < i_spoke < i_hub
    assert destroy.count("sweep-iam-guard.py") == 2
    assert "sweep-log-groups.py" in destroy
