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
