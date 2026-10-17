"""Hermetic unit tests for the logs / ecr / s3 reapers' migration onto
resilience.classify() / run_delete (issue #924 — section-by-section adoption).

No boto3, no network, no real sleeping. Each reaper is exercised with a tiny fake
client to assert the honest accounting the migration adds:
  * a real delete counts as deleted;
  * an already-gone resource is NOT counted as a delete we performed;
  * an AccessDenied is surfaced (logged + counted), never swallowed (#932), and
    the "nothing to delete" marker is NOT emitted when work was attempted.

Run:  python -m pytest workshop/scripts/tests/test_sweep_reapers.py -q
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sweep import resilience as r  # noqa: E402
from sweep.reapers import ecr as ecr_reaper  # noqa: E402
from sweep.reapers import s3 as s3_reaper  # noqa: E402
from sweep.reapers import logs as logs_reaper  # noqa: E402
from sweep.reapers import iam as iam_reaper  # noqa: E402
from sweep.reapers import rds as rds_reaper  # noqa: E402


class FakeClientError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


def _no_sleep(monkey=None):
    # run_delete → retry_aws defaults sleep=time.sleep; the classified cases here
    # (deleted/gone/access_denied/permanent) never retry, so no sleep happens.
    return None


class _EmptyPaginator:
    def paginate(self, *a, **k):
        return iter(())


def _ctx(**attrs):
    ns = types.SimpleNamespace(**attrs)
    ns._log_lines = []
    ns.log = lambda m: ns._log_lines.append(m)
    return ns


def _joined(ctx):
    return "\n".join(ctx._log_lines)


# ── ECR ───────────────────────────────────────────────────────────────────────

class _FakeEcr:
    def __init__(self, behavior):
        self._behavior = behavior  # callable(name) -> None | raises

    def delete_repository(self, repositoryName, force=False):
        return self._behavior(repositoryName)


def test_ecr_real_delete_counted():
    ctx = _ctx(prefix="peeks", ecr=_FakeEcr(lambda n: None))
    ecr_reaper.reap(ctx)
    out = _joined(ctx)
    assert "ECR: force-deleted 1 orphaned repository(ies)" in out
    assert "0 access-denied, 0 failed" in out


def test_ecr_already_gone_not_counted():
    def boom(n):
        raise FakeClientError("RepositoryNotFoundException", "does not exist")
    ctx = _ctx(prefix="peeks", ecr=_FakeEcr(boom))
    ecr_reaper.reap(ctx)
    out = _joined(ctx)
    assert "ECR: force-deleted 0 orphaned repository(ies)" in out
    assert "0 access-denied, 0 failed" in out


def test_ecr_access_denied_surfaced():
    def boom(n):
        raise FakeClientError("AccessDenied", "not authorized")
    ctx = _ctx(prefix="peeks", ecr=_FakeEcr(boom))
    ecr_reaper.reap(ctx)
    out = _joined(ctx)
    assert "ECR: force-deleted 0 orphaned repository(ies)" in out
    assert "1 access-denied" in out
    assert "ACCESS DENIED" in out


# ── S3 ──────────────────────────────────────────────────────────────────────────

class _FakeS3:
    def __init__(self, buckets, delete_behavior, region="us-west-2"):
        self._buckets = buckets
        self._delete = delete_behavior
        self._region = region

    def list_buckets(self):
        return {"Buckets": [{"Name": b} for b in self._buckets]}

    def get_bucket_location(self, Bucket):
        return {"LocationConstraint": self._region if self._region != "us-east-1" else None}

    def get_paginator(self, name):
        return _EmptyPaginator()

    def delete_objects(self, **k):
        return {}

    def delete_bucket(self, Bucket):
        return self._delete(Bucket)


def test_s3_no_buckets_marker_preserved():
    ctx = _ctx(prefix="peeks", region="us-west-2",
               s3=_FakeS3([], lambda b: None))
    s3_reaper.reap(ctx)
    assert "No orphaned S3 buckets to delete" in _joined(ctx)


def test_s3_real_delete_counted():
    ctx = _ctx(prefix="peeks", region="us-west-2",
               s3=_FakeS3(["peeks-ray-models-123", "unrelated-bucket"], lambda b: None))
    s3_reaper.reap(ctx)
    out = _joined(ctx)
    assert "S3: deleted 1 orphaned bucket(s)" in out  # only the prefix-matched one
    assert "No orphaned S3 buckets to delete" not in out


def test_s3_access_denied_not_reported_as_nothing():
    def boom(b):
        raise FakeClientError("AccessDenied", "not authorized")
    ctx = _ctx(prefix="peeks", region="us-west-2",
               s3=_FakeS3(["peeks-ray-models-123"], boom))
    s3_reaper.reap(ctx)
    out = _joined(ctx)
    # #932: a matched-but-denied bucket must NOT surface as "nothing to delete".
    assert "No orphaned S3 buckets to delete" not in out
    assert "1 access-denied" in out
    assert "ACCESS DENIED" in out


# ── CloudWatch Logs ───────────────────────────────────────────────────────────

class _LGPaginator:
    def __init__(self, groups):
        self._groups = groups

    def paginate(self, logGroupNamePrefix=None):
        matched = [g for g in self._groups if g.startswith(logGroupNamePrefix)]
        yield {"logGroups": [{"logGroupName": g} for g in matched]}


class _FakeLogs:
    def __init__(self, groups, delete_behavior):
        self._groups = groups
        self._delete = delete_behavior

    def get_paginator(self, name):
        return _LGPaginator(self._groups)

    def delete_log_group(self, logGroupName):
        return self._delete(logGroupName)

    # delivery objects: empty for the log-group tests
    def describe_delivery_sources(self):
        return {"deliverySources": []}

    def describe_deliveries(self):
        return {"deliveries": []}

    def describe_delivery_destinations(self):
        return {"deliveryDestinations": []}


def test_log_groups_no_match_marker_preserved():
    ctx = _ctx(prefix="peeks", hub="peeks-hub", spokes=[],
               logs=_FakeLogs([], lambda n: None))
    logs_reaper.reap_log_groups(ctx)
    assert "CloudWatch: no matching log groups found" in _joined(ctx)


def test_log_groups_access_denied_surfaced():
    def boom(n):
        raise FakeClientError("AccessDenied", "not authorized")
    ctx = _ctx(prefix="peeks", hub="peeks-hub", spokes=[],
               logs=_FakeLogs(["/aws/eks/peeks-hub/cluster"], boom))
    logs_reaper.reap_log_groups(ctx)
    out = _joined(ctx)
    assert "CloudWatch: deleted 0/1 log group(s)" in out
    assert "1 access-denied" in out
    assert "AccessDenied" in out


def test_log_groups_real_delete_counted():
    ctx = _ctx(prefix="peeks", hub="peeks-hub", spokes=[],
               logs=_FakeLogs(["/aws/eks/peeks-hub/cluster"], lambda n: None))
    logs_reaper.reap_log_groups(ctx)
    assert "CloudWatch: deleted 1/1 log group(s)" in _joined(ctx)


# ── IAM ───────────────────────────────────────────────────────────────────────

class _FakeIam:
    def __init__(self, role_names):
        self._roles = [{"RoleName": n} for n in role_names]
        self.deleted = []

    def get_paginator(self, op):
        roles = self._roles

        class _P:
            def paginate(self, **k):
                return iter([{"Roles": roles}] if op == "list_roles" else [{"Policies": []}])

        return _P()

    def list_attached_role_policies(self, RoleName):
        return {"AttachedPolicies": []}

    def list_role_policies(self, RoleName):
        return {"PolicyNames": []}

    def delete_role(self, RoleName):
        self.deleted.append(RoleName)


def test_iam_never_deletes_cloudformation_stack_roles():
    # Self-paced stack "peeks-workshop" and Workshop Studio "peeks-workshop-team-stack"
    # roles must survive; workshop-created roles are still reaped.
    iam = _FakeIam([
        "peeks-workshop-GitTokenSeedFnServiceRole2DC4919C-ABC",
        "peeks-workshop-PEEKSSharedRole61C60677-XYZ",
        "peeks-workshop-team-stack-IdeRole-123",
        "peeks-hub-argo-rollouts",
        "peeks-spoke-dev-ack-capability-role",
    ])
    ctx = _ctx(iam=iam, prefix="peeks", spokes=[])
    iam_reaper.reap(ctx)
    assert sorted(iam.deleted) == ["peeks-hub-argo-rollouts", "peeks-spoke-dev-ack-capability-role"]


# ── RDS (DevLake Aurora) ──────────────────────────────────────────────────────

class _FakeRds:
    """Stateful fake: delete removes from the live set so the reaper's drain polls
    resolve on the first attempt (hermetic, no sleeping)."""

    def __init__(self, instances=(), clusters=(), subnet_groups=(), protected=()):
        prot = set(protected)
        self.instances = {i: {"DBInstanceIdentifier": i, "DeletionProtection": i in prot} for i in instances}
        self.clusters = {c: {"DBClusterIdentifier": c, "DeletionProtection": c in prot} for c in clusters}
        self.subnet_groups = {s: {"DBSubnetGroupName": s} for s in subnet_groups}
        self.deleted = {"instances": [], "clusters": [], "subnet_groups": []}
        self.modified = []

    def describe_db_instances(self):
        return {"DBInstances": list(self.instances.values())}

    def describe_db_clusters(self):
        return {"DBClusters": list(self.clusters.values())}

    def describe_db_subnet_groups(self):
        return {"DBSubnetGroups": list(self.subnet_groups.values())}

    def modify_db_instance(self, **k):
        self.modified.append(("instance", k.get("DBInstanceIdentifier")))

    def modify_db_cluster(self, **k):
        self.modified.append(("cluster", k.get("DBClusterIdentifier")))

    def delete_db_instance(self, DBInstanceIdentifier, **k):
        self.instances.pop(DBInstanceIdentifier, None)
        self.deleted["instances"].append(DBInstanceIdentifier)

    def delete_db_cluster(self, DBClusterIdentifier, **k):
        self.clusters.pop(DBClusterIdentifier, None)
        self.deleted["clusters"].append(DBClusterIdentifier)

    def delete_db_subnet_group(self, DBSubnetGroupName, **k):
        self.subnet_groups.pop(DBSubnetGroupName, None)
        self.deleted["subnet_groups"].append(DBSubnetGroupName)


class _FakeEc2NoEni:
    def describe_network_interfaces(self, **k):
        return {"NetworkInterfaces": []}


def _force_stdlib_resilience():
    # No pip in the hermetic test: force resilience onto its stdlib shim so
    # ensure_tenacity() never shells out. The drain predicates return truthy on the
    # first attempt here, so neither run_delete nor poll_until ever sleeps.
    r._tenacity = None
    r._USING_STDLIB_FALLBACK = True


def test_rds_reaps_prefixed_devlake_aurora_and_subnet_group():
    # Regression for the real teardown bug: the DBs are named `<prefix>-devlake-*`,
    # so the old `startswith("devlake")` match missed them and the Aurora + its ENI
    # survived, failing the CFN VPC delete. The reaper must now delete the member
    # instance, the Aurora cluster, and the prefix-anchored devlake DB subnet group.
    # A BARE `devlake-*` subnet group (no VpcId / vpc_is_ours ownership signal) is
    # left alone — it could belong to another deployment (review #1051 §1).
    _force_stdlib_resilience()
    rds = _FakeRds(
        instances=["peeks-devlake-mysql-instance-1"],
        clusters=["peeks-devlake-mysql-cluster"],
        subnet_groups=["peeks-devlake-mysql-subnet-group", "devlake-mysql-subnet-group", "peeks-other-subnet-group"],
    )
    ctx = _ctx(rds=rds, ec2=_FakeEc2NoEni(), prefix="peeks")
    rds_reaper.reap(ctx)
    assert rds.deleted["instances"] == ["peeks-devlake-mysql-instance-1"]
    assert rds.deleted["clusters"] == ["peeks-devlake-mysql-cluster"]
    assert rds.deleted["subnet_groups"] == ["peeks-devlake-mysql-subnet-group"]
    assert "devlake-mysql-subnet-group" in rds.subnet_groups      # bare, unverified -> left alone
    assert "peeks-other-subnet-group" in rds.subnet_groups        # unrelated SG group untouched
    assert "ENI drained" in _joined(ctx)


def test_rds_does_not_touch_other_prefix_devlake():
    # review #1051 §1 (blocker): with prefix `peeks`, another deployment's
    # `acme-devlake-*` resources must NOT match. The old substring test would have
    # deleted them with deletion protection cleared and no final snapshot.
    _force_stdlib_resilience()
    rds = _FakeRds(
        instances=["acme-devlake-mysql-instance-1"],
        clusters=["acme-devlake-mysql-cluster"],
        subnet_groups=["acme-devlake-mysql-subnet-group"],
    )
    ctx = _ctx(rds=rds, ec2=_FakeEc2NoEni(), prefix="peeks")
    rds_reaper.reap(ctx)
    assert rds.deleted == {"instances": [], "clusters": [], "subnet_groups": []}
    assert "No DevLake RDS resources to delete" in _joined(ctx)


def test_rds_skips_deletion_protected_and_never_clears_it():
    # review #1051 §2 (high): a protected match is the strongest sign it isn't ours
    # (the workshop never sets protection). Skip it, log it, NEVER clear protection.
    _force_stdlib_resilience()
    rds = _FakeRds(
        instances=["peeks-devlake-mysql-instance-1"],
        clusters=["peeks-devlake-mysql-cluster"],
        subnet_groups=["peeks-devlake-mysql-subnet-group"],
        protected=["peeks-devlake-mysql-instance-1", "peeks-devlake-mysql-cluster"],
    )
    ctx = _ctx(rds=rds, ec2=_FakeEc2NoEni(), prefix="peeks")
    rds_reaper.reap(ctx)
    assert rds.deleted["instances"] == []
    assert rds.deleted["clusters"] == []
    assert rds.modified == []  # deletion protection never cleared
    assert "DeletionProtection=ON" in _joined(ctx)


def test_rds_rerun_deletes_leftover_subnet_group():
    # review #1051 §3 (medium): a re-run after the DBs are already gone, with only
    # the subnet group left, must still delete it (the old early-return skipped it).
    _force_stdlib_resilience()
    rds = _FakeRds(instances=[], clusters=[], subnet_groups=["peeks-devlake-mysql-subnet-group"])
    ctx = _ctx(rds=rds, ec2=_FakeEc2NoEni(), prefix="peeks")
    rds_reaper.reap(ctx)
    assert rds.deleted["subnet_groups"] == ["peeks-devlake-mysql-subnet-group"]


def test_rds_noop_when_no_devlake_resources():
    _force_stdlib_resilience()
    rds = _FakeRds(instances=["some-unrelated-db"], clusters=[], subnet_groups=[])
    ctx = _ctx(rds=rds, ec2=_FakeEc2NoEni(), prefix="peeks")
    rds_reaper.reap(ctx)
    assert rds.deleted["instances"] == []
    assert rds.deleted["clusters"] == []
    assert "No DevLake RDS resources to delete" in _joined(ctx)


def _eni(group_name, vpc_id):
    # An RDS/DevLake ENI as describe_network_interfaces returns it.
    return {"Description": "RDSNetworkInterface",
            "Groups": [{"GroupName": group_name}], "VpcId": vpc_id}


class _FakeEc2Eni:
    """ENI fake that returns the given interfaces and counts describe calls, so a
    test can assert whether the ENI-drain poll ran at all."""

    def __init__(self, enis=()):
        self._enis = list(enis)
        self.describe_calls = 0

    def describe_network_interfaces(self, **k):
        self.describe_calls += 1
        return {"NetworkInterfaces": self._enis}


def test_rds_cluster_access_denied_surfaced_and_not_waited_on():
    # The live teardown path (review #1051): the SharedRole CAN delete the instance
    # (freeing the ENI, which fixes the titled VPC DELETE_FAILED) but is REFUSED on
    # delete_db_cluster. Two guarantees: the AccessDenied is surfaced, never swallowed
    # (#932); and because the cluster delete was refused, step 5 must NOT burn its
    # full ~10 min cluster-gone poll on a cluster that will never disappear.
    _force_stdlib_resilience()

    class _RdsClusterDenied(_FakeRds):
        def delete_db_cluster(self, DBClusterIdentifier, **k):
            raise FakeClientError("AccessDenied", "not authorized to perform: rds:DeleteDBCluster")

    rds = _RdsClusterDenied(
        instances=["peeks-devlake-mysql-instance-1"],
        clusters=["peeks-devlake-mysql-cluster"],
        subnet_groups=["peeks-devlake-mysql-subnet-group"],
    )
    ctx = _ctx(rds=rds, ec2=_FakeEc2NoEni(), prefix="peeks")
    rds_reaper.reap(ctx)
    out = _joined(ctx)
    # The instance delete succeeded (this is what frees the ENI → titled bug fixed).
    assert rds.deleted["instances"] == ["peeks-devlake-mysql-instance-1"]
    # The cluster delete was refused and surfaced honestly, not swallowed.
    assert "peeks-devlake-mysql-cluster" not in rds.deleted["clusters"]
    assert "access_denied" in out and "AccessDenied" in out
    # The refused cluster is NOT waited on — no 10 min cluster-gone poll.
    assert "clusters still present after wait" not in out


def test_rds_eni_wait_skipped_when_no_db_deleted():
    # review #1051: a re-run with only the subnet group left deletes no instance or
    # cluster, so there is no ENI to drain — the ENI poll must not run at all. It
    # previously ran unconditionally and, with a co-tenant ENI present, burned the
    # full ceiling on a run that only had to drop a subnet group.
    _force_stdlib_resilience()
    ec2 = _FakeEc2Eni([_eni("acme-devlake-mysql-sg-1", "vpc-acme")])
    rds = _FakeRds(instances=[], clusters=[], subnet_groups=["peeks-devlake-mysql-subnet-group"])
    ctx = _ctx(rds=rds, ec2=ec2, prefix="peeks")
    rds_reaper.reap(ctx)
    assert rds.deleted["subnet_groups"] == ["peeks-devlake-mysql-subnet-group"]
    assert ec2.describe_calls == 0  # ENI poll never ran — nothing was deleted this run


def test_rds_eni_drain_ignores_other_deployments_eni():
    # review #1051: the ENI-drain predicate is scoped to THIS deployment. A co-tenant
    # `acme-devlake-*` ENI (different prefix, not our VPC) must not keep us waiting;
    # once our own DBs are deleted the drain is considered complete.
    _force_stdlib_resilience()
    ec2 = _FakeEc2Eni([_eni("acme-devlake-mysql-sg-1", "vpc-acme")])
    rds = _FakeRds(
        instances=["peeks-devlake-mysql-instance-1"],
        clusters=["peeks-devlake-mysql-cluster"],
        subnet_groups=["peeks-devlake-mysql-subnet-group"],
    )
    ctx = _ctx(rds=rds, ec2=ec2, prefix="peeks")
    rds_reaper.reap(ctx)
    assert ec2.describe_calls >= 1           # ENI poll DID run (a DB was deleted)
    assert "ENI drained" in _joined(ctx)     # ...and the co-tenant ENI was ignored


class _FakeRdsDeleting(_FakeRds):
    """DBs already in `deleting` state when §4 runs (ACK / `task destroy` got there
    first). Re-issuing a delete raises the RDS in-flight-state error; the resource
    disappears from describe after `drop_after` describe calls, modelling the delete
    actually completing so the cluster-gone poll and the subnet-group delete can make
    progress."""

    def __init__(self, drop_after=1, **kw):
        super().__init__(**kw)
        for v in self.instances.values():
            v["DBInstanceStatus"] = "deleting"
        for v in self.clusters.values():
            v["Status"] = "deleting"
        self._drop_after = drop_after
        self._inst_calls = 0
        self._clus_calls = 0

    def describe_db_instances(self):
        self._inst_calls += 1
        if self._inst_calls > self._drop_after:
            self.instances = {}
        return {"DBInstances": list(self.instances.values())}

    def describe_db_clusters(self):
        self._clus_calls += 1
        if self._clus_calls > self._drop_after:
            self.clusters = {}
        return {"DBClusters": list(self.clusters.values())}

    def delete_db_instance(self, DBInstanceIdentifier, **k):
        raise FakeClientError("InvalidDBInstanceState",
                              f"Instance {DBInstanceIdentifier} is already being deleted.")

    def delete_db_cluster(self, DBClusterIdentifier, **k):
        raise FakeClientError("InvalidDBClusterStateFault",
                              f"Cluster {DBClusterIdentifier} is in deleting state.")


def test_rds_already_deleting_db_is_waited_on_not_reissued():
    # review #1051 (blocking regression): when ACK / task destroy already started the
    # delete, the DB is in `deleting` state. The old accepted-delete gating treated the
    # re-issue (InvalidDB*StateFault -> 'permanent') as "nothing accepted", so it SKIPPED
    # the drain + cluster-gone polls, fired delete_db_cluster while members were still
    # deleting, and leaked the subnet group. §4 must instead treat an already-`deleting`
    # match as accepted: never re-issue the delete, keep the waits, and only delete the
    # subnet group once the cluster is actually gone (same rule §16c applies).
    _force_stdlib_resilience()
    rds = _FakeRdsDeleting(
        drop_after=1,
        instances=["peeks-devlake-mysql-instance"],
        clusters=["peeks-devlake-mysql-cluster"],
        subnet_groups=["peeks-devlake-mysql-subnet-group"],
    )
    ctx = _ctx(rds=rds, ec2=_FakeEc2NoEni(), prefix="peeks")
    rds_reaper.reap(ctx)
    out = _joined(ctx)
    # The in-flight deletes are NOT re-issued (no InvalidDB*StateFault 'permanent' line).
    assert "already deleting — not re-issued" in out
    assert "permanent (InvalidDBInstanceState)" not in out
    assert "permanent (InvalidDBClusterStateFault)" not in out
    # Both waits ran (the instance/cluster were treated as accepted) and the DBs drained.
    assert "ENI drained" in out
    # Once the cluster is gone, the subnet group deletes cleanly — no residue, no leak.
    assert rds.deleted["subnet_groups"] == ["peeks-devlake-mysql-subnet-group"]
    assert "left as residue" not in out


def test_rds_eni_drain_ignores_cotenant_prefix_superstring_sg():
    # review #1051 (ENI anchoring): the ENI ownership check must anchor on
    # `<prefix>-devlake` per group NAME, not as a substring of the joined group list.
    # A co-tenant whose own prefix CONTAINS ours (`team-peeks-devlake-mysql-sg-*` when
    # our prefix is `peeks`) must NOT read as ours, or every teardown waits the full
    # 580 s ceiling on a neighbour's ENI.
    _force_stdlib_resilience()
    ec2 = _FakeEc2Eni([_eni("team-peeks-devlake-mysql-sg-1", "vpc-cotenant")])
    rds = _FakeRds(
        instances=["peeks-devlake-mysql-instance-1"],
        clusters=["peeks-devlake-mysql-cluster"],
        subnet_groups=["peeks-devlake-mysql-subnet-group"],
    )
    ctx = _ctx(rds=rds, ec2=ec2, prefix="peeks")
    rds_reaper.reap(ctx)
    # Our own DBs deleted, co-tenant's superstring-prefix ENI ignored -> drain completes.
    assert ec2.describe_calls >= 1
    assert "ENI drained" in _joined(ctx)
