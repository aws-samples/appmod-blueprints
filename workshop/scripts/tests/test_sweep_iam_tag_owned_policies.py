"""Hermetic tests for the §7 IAM reaper on unprefixed, tag-owned customer-managed policies.

Live case: the HuggingFaceModel RGD names its S3 policy <model>-s3-policy on the default
prefix (gpt2-neuron-s3-policy, mistral-7b-neuron-s3-policy, tinyllama-s3-policy). The
policy carried no platform.gitops.io/prefix tag (only the role did), destroy's shared-IAM
guard retains it (outside <prefix>-), and the sweep's policy loop matched names only, so the
three policies stayed in the account, unattached, after the teardown.

A policy outside the prefix is now deleted only when it carries the prefix tag or was
created by our hub's ACK capability, carries no CloudFormation tag, and is attached to
nothing. §17 reports any such policy still present.

Run:  python -m pytest workshop/scripts/tests/test_sweep_iam_tag_owned_policies.py -q
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_sweep_orchestration as orch  # noqa: E402

ACCT = "111122223333"
PFX = "platform.gitops.io/prefix"
CAP = "eks:eks-capability-arn"


def _cap(hub):
    return f"arn:aws:eks:us-west-2:{ACCT}:capability/{hub}/ack/abc123"


# name -> (AttachmentCount, tags)
POLICIES = {
    "gpt2-neuron-s3-policy": (0, {PFX: "peeks"}),                  # new RGD: tagged
    "mistral-7b-neuron-s3-policy": (0, {CAP: _cap("peeks-hub")}),  # legacy: our capability
    "tinyllama-s3-policy": (0, {CAP: _cap("peeks-hub")}),
    "peeks-spoke-dev-lbc-policy": (0, {}),                         # by name, as before
    # never ours
    "other-s3-policy": (0, {PFX: "pvt"}),
    "team-s3-policy": (0, {CAP: _cap("team-peeks-hub")}),
    "shared-s3-policy": (1, {PFX: "peeks"}),                       # still attached
    "ws-default-policy": (0, {}),
    "cfn-s3-policy": (0, {PFX: "peeks", "aws:cloudformation:stack-name": "peeks-workshop-team-stack"}),
    "peeks-workshop-team-stack-Policy-ABC": (0, {PFX: "peeks"}),   # the stack's own (skip)
}
OURS = {"gpt2-neuron-s3-policy", "mistral-7b-neuron-s3-policy", "tinyllama-s3-policy",
        "peeks-spoke-dev-lbc-policy"}


def _arn(n):
    return f"arn:aws:iam::{ACCT}:policy/{n}"


class _Pages:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, *a, **k):
        return iter(self.pages)


class FakeIam(orch.FakeClient):
    def __init__(self, fail_tags=False):
        super().__init__("iam")
        self.policies = dict(POLICIES)
        self.deleted = []
        self.fail_tags = fail_tags

    def get_paginator(self, name):
        if name == "list_policies":
            return _Pages([{"Policies": [{"PolicyName": n, "Arn": _arn(n), "AttachmentCount": c}
                                         for n, (c, _t) in self.policies.items()]}])
        if name == "list_roles":
            return _Pages([{"Roles": []}])
        return orch._Paginator()

    def list_policy_tags(self, PolicyArn):
        if self.fail_tags:
            raise RuntimeError("AccessDenied")
        return {"Tags": [{"Key": k, "Value": v}
                         for k, v in self.policies[PolicyArn.rsplit("/", 1)[-1]][1].items()]}

    def list_policy_versions(self, PolicyArn):
        return {"Versions": [{"VersionId": "v1", "IsDefaultVersion": True}]}

    def delete_policy(self, PolicyArn):
        n = PolicyArn.rsplit("/", 1)[-1]
        self.deleted.append(n)
        self.policies.pop(n)


def _ctx(iam):
    def f(service, **kw):
        return iam if service == "iam" else orch.FakeClient(service)
    with mock.patch("sweep.context.boto3.client", side_effect=f):
        from sweep.context import SweepContext
        return SweepContext("us-west-2", "peeks"), f


class TagOwnedPolicyTest(unittest.TestCase):
    def test_deletes_only_our_unattached_policies(self):
        from sweep.reapers import iam as iam_reaper
        fake = FakeIam()
        ctx, _f = _ctx(fake)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            iam_reaper.reap(ctx)
        self.assertEqual(set(fake.deleted), OURS, buf.getvalue())
        self.assertIn("Deleted 3 unprefixed IAM policy(ies) owned by tag", buf.getvalue())

    def test_tag_lookup_failure_takes_nothing_outside_the_prefix(self):
        from sweep.reapers import iam as iam_reaper
        fake = FakeIam(fail_tags=True)
        ctx, _f = _ctx(fake)
        with contextlib.redirect_stdout(io.StringIO()):
            iam_reaper.reap(ctx)
        self.assertEqual(fake.deleted, ["peeks-spoke-dev-lbc-policy"])

    def test_gate_reports_leftover_and_full_run_is_clean_after_reap(self):
        from sweep.reapers import iam as iam_reaper
        fake = FakeIam()
        ctx, f = _ctx(fake)
        self.assertEqual(sorted(iam_reaper.owned_orphan_policies(ctx)),
                         ["gpt2-neuron-s3-policy", "mistral-7b-neuron-s3-policy", "tinyllama-s3-policy"])
        with mock.patch("sweep.context.boto3.client", side_effect=f), \
             mock.patch("time.sleep", lambda s: None):
            from sweep.orchestrator import main
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main("us-west-2", "peeks")
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertNotIn("iam-policy:", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
