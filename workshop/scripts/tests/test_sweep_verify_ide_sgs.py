"""Hermetic test for the §17 completeness gate: a security group left in the IDE VPC that
CloudFormation does not own is residue, tagged by us or not.

Live case: the AMG workspace SG (peeks-amg-sg, no platform.gitops.io/prefix tag) stayed in
the IDE VPC, the gate printed "DESTROY COMPLETE" (rc=0), and the CloudFormation delete of
the IDE VPC then failed on it. CFN-owned SGs and the default SG are not residue: CFN deletes
them itself after the sweep.

Run:  python -m pytest workshop/scripts/tests/test_sweep_verify_ide_sgs.py -q
Set SWEEP_SCRIPTS_DIR=<dir> to run the same checks against another copy of the sweep.
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = os.environ.get("SWEEP_SCRIPTS_DIR") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_sweep_orchestration as orch  # noqa: E402

if os.environ.get("SWEEP_SCRIPTS_DIR"):  # standalone run against another copy only
    sys.path.insert(0, SCRIPTS_DIR)
    for _m in [m for m in sys.modules if m == "sweep" or m.startswith("sweep.")]:
        del sys.modules[_m]

IDE_VPC = {"VpcId": "vpc-ide", "Tags": [
    {"Key": "aws:cloudformation:stack-name", "Value": "peeks-workshop-team-stack"},
    {"Key": "platform.gitops.io/prefix", "Value": "peeks"}]}
CFN_SG = {"GroupId": "sg-cfn", "GroupName": "IdeSecurityGroup",
          "Tags": [{"Key": "aws:cloudformation:stack-name", "Value": "peeks-workshop-team-stack"}]}
DEFAULT_SG = {"GroupId": "sg-default", "GroupName": "default", "Tags": []}
AMG_SG = {"GroupId": "sg-amg", "GroupName": "peeks-amg-sg", "Tags": []}


class _DependencyViolation(Exception):
    def __init__(self):
        super().__init__("DependencyViolation")
        self.response = {"Error": {"Code": "DependencyViolation", "Message": "dependent object"}}


class FakeEc2(orch.FakeClient):
    def __init__(self, sgs, stuck):
        super().__init__("ec2")
        self.sgs, self.stuck = list(sgs), stuck

    def describe_vpcs(self, VpcIds=None, Filters=None, **_):
        if Filters:  # the spoke/owned VPC scans: the IDE VPC is CFN-owned, skipped anyway
            return {"Vpcs": []}
        return {"Vpcs": [IDE_VPC]}

    def describe_security_groups(self, Filters=None, **_):
        return {"SecurityGroups": list(self.sgs)}

    def delete_security_group(self, GroupId):
        if self.stuck:
            raise _DependencyViolation()
        self.sgs = [s for s in self.sgs if s["GroupId"] != GroupId]


def _run(sgs, stuck):
    ec2 = FakeEc2(sgs, stuck)

    def factory(service, **kw):
        return ec2 if service == "ec2" else orch.FakeClient(service)

    from sweep import resilience
    real = resilience.poll_until

    def no_sleep_poll(pred, *, attempts, delay, backoff=1.0, sleep=None):
        return real(pred, attempts=attempts, delay=delay, backoff=backoff, sleep=lambda s: None)

    with mock.patch("sweep.context.boto3.client", side_effect=factory), \
         mock.patch("sweep.reapers.resweep.poll_until", no_sleep_poll), \
         mock.patch("time.sleep", lambda s: None):
        from sweep.orchestrator import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main("us-west-2", "peeks")
    return rc, buf.getvalue()


class VerifyIdeSgTest(unittest.TestCase):
    def test_untagged_sg_left_in_ide_vpc_is_residue(self):
        rc, out = _run([CFN_SG, DEFAULT_SG, AMG_SG], stuck=True)
        self.assertEqual(rc, 1, msg=out)
        self.assertIn("DESTROY INCOMPLETE", out)
        self.assertIn("sg:vpc-ide/sg-amg(peeks-amg-sg)", out)

    def test_cfn_owned_and_default_sgs_are_not_residue(self):
        rc, out = _run([CFN_SG, DEFAULT_SG], stuck=True)
        self.assertEqual(rc, 0, msg=out)
        self.assertIn("DESTROY COMPLETE", out)
        self.assertNotIn("sg:vpc-ide", out)

    def test_deleted_sg_is_not_residue(self):
        rc, out = _run([CFN_SG, DEFAULT_SG, AMG_SG], stuck=False)
        self.assertEqual(rc, 0, msg=out)
        self.assertNotIn("sg:vpc-ide", out)


if __name__ == "__main__":
    unittest.main()
