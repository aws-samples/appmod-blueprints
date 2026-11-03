"""Hermetic tests for the §16c residue net and its §17 gate counterpart (R-27).

After a cold destroy (task destroy skipped) the sweep left PVC volumes, ECR <prefix>/*,
DynamoDB tables, SSM parameters and fluent-bit log groups, and the gate did not see them.
In-memory fake clients only: no boto3, no network, no sleeping.

Run:  python -m pytest workshop/scripts/tests/test_sweep_residue.py -q
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sweep.reapers import iam as iam_reaper  # noqa: E402
from sweep.reapers import residue  # noqa: E402
from sweep.reapers import verify  # noqa: E402

PFX = "peeks"


class AwsError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


class _Pager:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kw):
        return iter(self._pages(kw) if callable(self._pages) else self._pages)


def _match_tag(v, flt):
    name, vals = flt["Name"], flt["Values"]
    tags = {t["Key"]: t["Value"] for t in v.get("Tags", [])}
    if name == "status":
        return v["State"] in vals
    if name == "tag-key":
        return any(_glob(k, vals) for k in tags)
    if name.startswith("tag:"):
        return name[4:] in tags and _glob(tags[name[4:]], vals)
    return True


def _glob(s, patterns):
    for p in patterns:
        if p.endswith("*") and s.startswith(p[:-1]) or s == p:
            return True
    return False


class FakeEc2:
    def __init__(self, volumes):
        self.volumes = {v["VolumeId"]: v for v in volumes}
        self.deleted = []
        self.deny = set()

    def get_paginator(self, name):
        assert name == "describe_volumes"

        def pages(kw):
            vols = [v for v in self.volumes.values()
                    if all(_match_tag(v, f) for f in kw.get("Filters", []))]
            return [{"Volumes": vols}]
        return _Pager(pages)

    def describe_volumes(self, VolumeIds):
        vols = [self.volumes[i] for i in VolumeIds if i in self.volumes]
        if not vols:
            raise AwsError("InvalidVolume.NotFound", f"The volume '{VolumeIds[0]}' does not exist.")
        return {"Volumes": vols}

    def delete_volume(self, VolumeId):
        if VolumeId in self.deny:
            raise AwsError("UnauthorizedOperation", "no")
        self.deleted.append(VolumeId)
        self.volumes.pop(VolumeId, None)


def vol(vid, tags, state="available", attached=False):
    return {"VolumeId": vid, "State": state,
            "Attachments": [{"InstanceId": "i-1"}] if attached else [],
            "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}


class FakeEks:
    def __init__(self, live=(), fail=False):
        self.live, self.fail = list(live), fail

    def get_paginator(self, name):
        if self.fail:
            raise AwsError("AccessDeniedException", "no")
        return _Pager([{"clusters": self.live}])


class FakeEcr:
    def __init__(self, repos):
        self.repos = set(repos)
        self.deleted = []

    def get_paginator(self, name):
        return _Pager(lambda kw: [{"repositories": [{"repositoryName": r} for r in sorted(self.repos)]}])

    def describe_repositories(self, repositoryNames):
        if repositoryNames[0] not in self.repos:
            raise AwsError("RepositoryNotFoundException", "does not exist")
        return {"repositories": [{"repositoryName": repositoryNames[0]}]}

    def delete_repository(self, repositoryName, force=False):
        assert force is True
        if repositoryName not in self.repos:
            raise AwsError("RepositoryNotFoundException", "does not exist")
        self.repos.discard(repositoryName)
        self.deleted.append(repositoryName)


class FakeDdb:
    def __init__(self, tables, protected=()):
        self.tables = set(tables)
        self.protected = set(protected)
        self.deleted = []

    def get_paginator(self, name):
        return _Pager(lambda kw: [{"TableNames": sorted(self.tables)}])

    def describe_table(self, TableName):
        if TableName not in self.tables:
            raise AwsError("ResourceNotFoundException", "not found")
        return {"Table": {"TableName": TableName, "DeletionProtectionEnabled": TableName in self.protected}}

    def delete_table(self, TableName):
        self.tables.discard(TableName)
        self.deleted.append(TableName)


class FakeSsm:
    def __init__(self, names):
        self.names = set(names)
        self.deleted = []

    def get_paginator(self, name):
        def pages(kw):
            root = kw["ParameterFilters"][0]["Values"][0]
            return [{"Parameters": [{"Name": n} for n in sorted(self.names) if n.startswith(root)]}]
        return _Pager(pages)

    def get_parameter(self, Name):
        if Name not in self.names:
            raise AwsError("ParameterNotFound", "not found")
        return {"Parameter": {"Name": Name}}

    def delete_parameter(self, Name):
        self.names.discard(Name)
        self.deleted.append(Name)


class FakeLogs:
    def __init__(self, groups):
        self.groups = set(groups)
        self.deleted = []

    def get_paginator(self, name):
        return _Pager(lambda kw: [{"logGroups": [{"logGroupName": g} for g in sorted(self.groups)
                                                 if g.startswith(kw["logGroupNamePrefix"])]}])

    def describe_log_groups(self, logGroupNamePrefix):
        return {"logGroups": [{"logGroupName": g} for g in self.groups if g.startswith(logGroupNamePrefix)]}

    def delete_log_group(self, logGroupName):
        self.groups.discard(logGroupName)
        self.deleted.append(logGroupName)


def make_ctx(ec2=None, ecr=None, ddb=None, ssm=None, logs=None, eks=None, dry_run=False, prefix=PFX):
    ns = types.SimpleNamespace(
        prefix=prefix, hub=f"{prefix}-hub", spokes=[f"{prefix}-spoke-dev"],
        ec2=ec2 or FakeEc2([]), ecr=ecr or FakeEcr([]), ddb=ddb or FakeDdb([]),
        ssm=ssm or FakeSsm([]), logs=logs or FakeLogs([]), eks=eks or FakeEks(),
        dry_run=dry_run, OWNER_PREFIX_TAG="platform.gitops.io/prefix")
    ns.lines = []
    ns.log = ns.lines.append
    ns.owned_clusters = lambda: {ns.hub, *ns.spokes}
    return ns


def text(ctx):
    return "\n".join(ctx.lines)


# ── EBS ───────────────────────────────────────────────────────────────────────

def test_ebs_deletes_only_available_prefixed_pvc_volumes():
    ec2 = FakeEc2([
        vol("vol-a", {"kubernetes.io/cluster/peeks-hub": "owned"}),
        vol("vol-b", {"ebs.csi.eks.amazonaws.com/cluster": "peeks-spoke-dev"}),
        vol("vol-c", {"kubernetes.io/cluster/peeks-hub": "owned"}, state="in-use", attached=True),
        vol("vol-d", {"kubernetes.io/cluster/other-hub": "owned"}),          # other prefix
        vol("vol-e", {"kubernetes.io/cluster/peeksx-hub": "owned"}),         # prefix only starts with ours
        vol("vol-f", {"Name": "peeks-something"}),                           # name alone is not ownership
        vol("vol-g", {}),
    ])
    ctx = make_ctx(ec2=ec2)
    residue.reap(ctx)
    assert sorted(ec2.deleted) == ["vol-a", "vol-b"]
    assert set(ec2.volumes) == {"vol-c", "vol-d", "vol-e", "vol-f", "vol-g"}


def test_ebs_volume_of_a_live_foreign_cluster_is_left_alone():
    ec2 = FakeEc2([vol("vol-a", {"kubernetes.io/cluster/peeks-b-hub": "owned"}),
                   vol("vol-b", {"kubernetes.io/cluster/peeks-hub": "owned"})])
    ctx = make_ctx(ec2=ec2, eks=FakeEks(live=["peeks-b-hub"]))
    residue.reap(ctx)
    assert ec2.deleted == ["vol-b"]
    assert "belong to a live cluster that is not ours" in text(ctx)


def test_ebs_fail_closed_when_clusters_cannot_be_listed():
    ec2 = FakeEc2([vol("vol-a", {"kubernetes.io/cluster/peeks-hub": "owned"})])
    ctx = make_ctx(ec2=ec2, eks=FakeEks(fail=True))
    residue.reap(ctx)
    assert ec2.deleted == []


def test_ebs_access_denied_is_counted_not_swallowed():
    ec2 = FakeEc2([vol("vol-a", {"kubernetes.io/cluster/peeks-hub": "owned"})])
    ec2.deny.add("vol-a")
    ctx = make_ctx(ec2=ec2)
    residue.reap(ctx)
    assert "Residue/ebs: deleted 0/1; 0 already gone, 1 access-denied, 0 failed" in text(ctx)


# ── ECR / DynamoDB / SSM / log groups ─────────────────────────────────────────────

def test_ecr_only_prefix_slash_repos_force_deleted():
    ecr = FakeEcr(["peeks/rust", "peeks/rust/cache", "peeks/java", "peeks/java/cache",
                   "peeksx/rust", "other/rust", "peeks-ray-vllm-custom", "rust"])
    ctx = make_ctx(ecr=ecr)
    residue.reap(ctx)
    assert sorted(ecr.deleted) == ["peeks/java", "peeks/java/cache", "peeks/rust", "peeks/rust/cache"]
    assert ecr.repos == {"peeksx/rust", "other/rust", "peeks-ray-vllm-custom", "rust"}


def test_dynamodb_only_prefix_dash_tables_and_never_protected_ones():
    ddb = FakeDdb(["peeks-table", "peeks-rust-app-table-dev", "peeks-rust-app-table-prod",
                   "peeksx-table", "other-table", "peeks", "peeks-keep"], protected=["peeks-keep"])
    ctx = make_ctx(ddb=ddb)
    residue.reap(ctx)
    assert sorted(ddb.deleted) == ["peeks-rust-app-table-dev", "peeks-rust-app-table-prod", "peeks-table"]
    assert ddb.tables == {"peeksx-table", "other-table", "peeks", "peeks-keep"}
    assert "deletion protection is on" in text(ctx)


def test_ssm_only_prefix_slash_parameters():
    ssm = FakeSsm(["/peeks/init-error", "/peeks/init-status", "/peeks/keycloak-idc-integration-credentials",
                   "/peeksx/init-status", "/other/x", "peeks-no-slash"])
    ctx = make_ctx(ssm=ssm)
    residue.reap(ctx)
    assert sorted(ssm.deleted) == ["/peeks/init-error", "/peeks/init-status",
                                   "/peeks/keycloak-idc-integration-credentials"]
    assert ssm.names == {"/peeksx/init-status", "/other/x", "peeks-no-slash"}


def test_fluentbit_log_groups_only_prefix_dash():
    root = "/aws/eks/fluentbit-cloudwatch/"
    logs = FakeLogs([root + "peeks-spoke-dev/logs", root + "peeks-spoke-prod/logs",
                     root + "peeksx-spoke/logs", root + "other-spoke/logs", "/aws/eks/peeks-hub/cluster"])
    ctx = make_ctx(logs=logs)
    residue.reap(ctx)
    assert sorted(logs.deleted) == [root + "peeks-spoke-dev/logs", root + "peeks-spoke-prod/logs"]
    assert root + "peeksx-spoke/logs" in logs.groups and root + "other-spoke/logs" in logs.groups


def test_dry_run_deletes_nothing_and_says_so():
    ec2 = FakeEc2([vol("vol-a", {"kubernetes.io/cluster/peeks-hub": "owned"})])
    ecr, ddb, ssm = FakeEcr(["peeks/rust"]), FakeDdb(["peeks-table"]), FakeSsm(["/peeks/x"])
    logs = FakeLogs(["/aws/eks/fluentbit-cloudwatch/peeks-spoke-dev/logs"])
    ctx = make_ctx(ec2=ec2, ecr=ecr, ddb=ddb, ssm=ssm, logs=logs, dry_run=True)
    residue.reap(ctx)
    assert not (ec2.deleted or ecr.deleted or ddb.deleted or ssm.deleted or logs.deleted)
    assert "[dry-run] would delete ECR repository peeks/rust" in text(ctx)


def test_another_prefix_is_never_touched():
    ec2 = FakeEc2([vol("vol-a", {"kubernetes.io/cluster/peeks-hub": "owned"})])
    ctx = make_ctx(ec2=ec2, ecr=FakeEcr(["peeks/rust"]), ddb=FakeDdb(["peeks-table"]),
                   ssm=FakeSsm(["/peeks/x"]), prefix="tdv")
    residue.reap(ctx)
    assert not (ec2.deleted or ctx.ecr.deleted or ctx.ddb.deleted or ctx.ssm.deleted)


def test_a_listing_error_does_not_stop_the_other_families():
    ecr = FakeEcr(["peeks/rust"])
    ddb = FakeDdb(["peeks-table"])
    ddb.get_paginator = lambda name: (_ for _ in ()).throw(AwsError("AccessDeniedException", "no"))
    ctx = make_ctx(ecr=ecr, ddb=ddb)
    residue.reap(ctx)
    assert ecr.deleted == ["peeks/rust"]
    assert "Residue/dynamodb: listing failed" in text(ctx)


# ── §17 gate ──────────────────────────────────────────────────────────────────

def test_gate_inventories_the_residue_families():
    ctx = make_ctx(
        ec2=FakeEc2([vol("vol-a", {"kubernetes.io/cluster/peeks-hub": "owned"})]),
        ecr=FakeEcr(["peeks/rust"]), ddb=FakeDdb(["peeks-table"]),
        ssm=FakeSsm(["/peeks/init-status"]),
        logs=FakeLogs(["/aws/eks/fluentbit-cloudwatch/peeks-spoke-dev/logs"]))
    found, errors = residue.enumerate_families(ctx)
    assert not errors
    assert found == {"ebs": ["vol-a"], "ecr": ["peeks/rust"], "dynamodb": ["peeks-table"],
                     "ssm": ["/peeks/init-status"],
                     "log-group": ["/aws/eks/fluentbit-cloudwatch/peeks-spoke-dev/logs"]}


def test_gate_ignores_a_resource_that_disappeared_after_listing():
    ctx = make_ctx(ec2=FakeEc2([]), ecr=FakeEcr([]), ddb=FakeDdb([]), ssm=FakeSsm([]), logs=FakeLogs([]))
    for fam, ident in (("ebs", "vol-0123"), ("ecr", "peeks/rust"), ("dynamodb", "peeks-table"),
                       ("ssm", "/peeks/x"), ("log-group", "/aws/eks/fluentbit-cloudwatch/peeks-a/logs")):
        assert residue.still_exists(ctx, fam, ident) is False, fam


def test_gate_keeps_a_resource_whose_lookup_is_denied():
    ctx = make_ctx()
    ctx.ddb.describe_table = lambda TableName: (_ for _ in ()).throw(AwsError("AccessDeniedException", "no"))
    assert residue.still_exists(ctx, "dynamodb", "peeks-table") is True


def test_tagged_volume_that_no_longer_exists_is_not_residue():
    ctx = make_ctx(ec2=FakeEc2([vol("vol-live", {})]))
    assert verify._tagged_arn_exists(ctx, "arn:aws:ec2:us-west-2:111122223333:volume/vol-gone") is False
    assert verify._tagged_arn_exists(ctx, "arn:aws:ec2:us-west-2:111122223333:volume/vol-live") is True
    # other types are never second-guessed
    assert verify._tagged_arn_exists(ctx, "arn:aws:eks:us-west-2:111122223333:cluster/peeks-hub") is True


def test_verify_run_reports_live_residue_and_drops_the_vanished_tagged_volume():
    ctx = make_ctx(ddb=FakeDdb(["peeks-table"]), ssm=FakeSsm(["/peeks/init-status"]))
    ctx.region = "us-west-2"
    ctx.ec2.get_paginator = lambda name: _Pager([{"Volumes": []}])
    ctx.ec2.describe_addresses = lambda **k: {"Addresses": []}
    ctx.ec2.describe_vpcs = lambda **k: {"Vpcs": []}
    ctx.s3 = types.SimpleNamespace(list_buckets=lambda: {"Buckets": []})
    ctx.sm = types.SimpleNamespace(get_paginator=lambda n: _Pager([{"SecretList": []}]))
    ctx.eip_is_ours = lambda tags: False
    ctx.discover_by_tag = lambda: [
        ("arn:aws:ec2:us-west-2:111122223333:volume/vol-gone", {"platform.gitops.io/prefix": "peeks"})]
    res = verify.run(ctx)
    assert res == ["dynamodb:peeks-table", "ssm:/peeks/init-status"]
    assert "DESTROY INCOMPLETE" in text(ctx)
    assert "vol-gone no longer exists" in text(ctx)


def test_verify_run_is_complete_when_the_families_are_empty():
    ctx = make_ctx()
    ctx.region = "us-west-2"
    ctx.ec2.get_paginator = lambda name: _Pager([{"Volumes": []}])
    ctx.ec2.describe_addresses = lambda **k: {"Addresses": []}
    ctx.ec2.describe_vpcs = lambda **k: {"Vpcs": []}
    ctx.s3 = types.SimpleNamespace(list_buckets=lambda: {"Buckets": []})
    ctx.sm = types.SimpleNamespace(get_paginator=lambda n: _Pager([{"SecretList": []}]))
    ctx.eip_is_ours = lambda tags: False
    ctx.discover_by_tag = lambda: []
    assert verify.run(ctx) == []
    assert "DESTROY COMPLETE" in text(ctx)


# ── IAM roles outside the prefix, owned by tag ───────────────────────────────────

class FakeIam:
    def __init__(self, roles):
        self.roles = roles  # name -> {"Path", "Tags"}
        self.deleted = []

    def get_paginator(self, name):
        if name == "list_roles":
            return _Pager([{"Roles": [{"RoleName": n, "Path": r.get("Path", "/")} for n, r in self.roles.items()]}])
        return _Pager([{"Policies": []}])

    def list_role_tags(self, RoleName):
        return {"Tags": [{"Key": k, "Value": v} for k, v in self.roles[RoleName].get("Tags", {}).items()]}

    def list_attached_role_policies(self, RoleName):
        return {"AttachedPolicies": []}

    def list_role_policies(self, RoleName):
        return {"PolicyNames": []}

    def delete_role(self, RoleName):
        self.deleted.append(RoleName)


def test_iam_tagged_roles_without_the_prefix_are_reaped_and_only_those():
    own = {"platform.gitops.io/prefix": "peeks"}
    iam = FakeIam({
        "gpt2-neuron-role": {"Tags": own},
        "tinyllama-role": {"Tags": own},
        "agent-cw-observability-role": {"Tags": own},
        "peeks-hub-role": {},                                             # by name, as before
        "mistral-7b-neuron-role": {"Tags": {"platform.gitops.io/prefix": "tdv"}},   # other stack
        "untagged-role": {},
        "cfn-role": {"Tags": {**own, "aws:cloudformation:stack-name": "x"}},       # CFN-managed
        "AWSServiceRoleForX": {"Path": "/aws-service-role/x/", "Tags": own},       # service-linked
        "peeks-workshop-team-stack-SharedRole-1": {"Tags": own},                   # stack's own
    })
    ctx = make_ctx()
    ctx.iam = iam
    iam_reaper.reap(ctx)
    assert sorted(iam.deleted) == ["agent-cw-observability-role", "gpt2-neuron-role",
                                   "peeks-hub-role", "tinyllama-role"]


def test_iam_tag_lookup_failure_leaves_the_role():
    iam = FakeIam({"tinyllama-role": {}})
    iam.list_role_tags = lambda RoleName: (_ for _ in ()).throw(AwsError("AccessDenied", "no"))
    ctx = make_ctx()
    ctx.iam = iam
    iam_reaper.reap(ctx)
    assert iam.deleted == []
    assert "tag lookup(s) failed" in text(ctx)
