"""Hermetic test for the final re-sweep (§16): the IDE VPC security groups are re-cleared
AFTER the ENI gate, and retried while their ENIs release.

Live case: the AMG workspace is deleted (§11), its ENIs go ~2 min later. §15 and the old
§16e both tried to delete its SG (peeks-amg-sg) while the ENIs were still there and got
DependencyViolation; §16f then waited for the CloudFront ENIs and nothing tried the SG
again, so it blocked the CloudFormation delete of the IDE VPC (DELETE_FAILED).

The fake EC2 runs on a virtual clock advanced by the poll sleeps: no AWS, no real sleep.
Run:  python -m pytest workshop/scripts/tests/test_sweep_resweep_sg_order.py -q
Set SWEEP_SCRIPTS_DIR=<dir> to run the same checks against another copy of the sweep.
"""
import io
import contextlib
import os
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = os.environ.get("SWEEP_SCRIPTS_DIR") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_sweep_orchestration as orch  # noqa: E402  (puts its own sweep dir on sys.path)

if os.environ.get("SWEEP_SCRIPTS_DIR"):  # standalone run against another copy only
    sys.path.insert(0, SCRIPTS_DIR)
    for _m in [m for m in sys.modules if m == "sweep" or m.startswith("sweep.")]:
        del sys.modules[_m]

VPC = "vpc-ide"


class _DependencyViolation(Exception):
    def __init__(self):
        super().__init__("DependencyViolation")
        self.response = {"Error": {"Code": "DependencyViolation", "Message": "has a dependent object"}}


class FakeEc2(orch.FakeClient):
    """ENIs present until their release time on the virtual clock; an SG with an ENI still
    attached cannot be deleted."""

    def __init__(self, clock, amg_eni_gone_at, cf_eni_gone_at):
        super().__init__("ec2")
        self.clock = clock
        self.eni = {"eni-amg": (amg_eni_gone_at, "interface", "sg-amg"),
                    "eni-cf": (cf_eni_gone_at, "cloudfront_managed", None)}
        self.sgs = {"sg-amg": "peeks-amg-sg"}
        self.delete_attempts = []

    def _live_enis(self):
        return {k: v for k, v in self.eni.items() if self.clock["t"] < v[0]}

    def describe_network_interfaces(self, Filters=None, **_):
        return {"NetworkInterfaces": [{"NetworkInterfaceId": k, "InterfaceType": t, "Description": ""}
                                      for k, (_g, t, _s) in self._live_enis().items()]}

    def describe_security_groups(self, Filters=None, **_):
        return {"SecurityGroups": [{"GroupId": g, "GroupName": n, "Tags": []} for g, n in self.sgs.items()]}

    def delete_security_group(self, GroupId):
        self.delete_attempts.append((self.clock["t"], GroupId))
        if any(s == GroupId for _g, _t, s in self._live_enis().values()):
            raise _DependencyViolation()
        self.sgs.pop(GroupId, None)


def _ctx(ec2):
    with mock.patch("sweep.context.boto3.client", side_effect=orch._fake_client):
        from sweep.context import SweepContext
        ctx = SweepContext("us-west-2", "peeks")
    ctx.ec2 = ec2
    ctx.hub_vpc_id = VPC
    return ctx


def _run(amg_eni_gone_at, cf_eni_gone_at):
    clock = {"t": 0.0}
    ec2 = FakeEc2(clock, amg_eni_gone_at, cf_eni_gone_at)
    ctx = _ctx(ec2)
    from sweep import resilience
    from sweep.reapers import resweep, vpc

    real = resilience.poll_until

    def virtual_poll(pred, *, attempts, delay, backoff=1.0, sleep=None):
        def _sleep(s):
            clock["t"] += s
        return real(pred, attempts=attempts, delay=delay, backoff=backoff, sleep=_sleep)

    buf = io.StringIO()
    with mock.patch.object(resweep, "poll_until", virtual_poll), \
         mock.patch("time.sleep", lambda s: clock.__setitem__("t", clock["t"] + s)), \
         contextlib.redirect_stdout(buf):
        vpc.reap_ide_sgs(ctx)   # §15 (fails: ENI still there)
        resweep.run(ctx)        # §16
    return ec2, buf.getvalue()


class ResweepSgOrderTest(unittest.TestCase):
    def test_sg_released_during_the_eni_gate_is_deleted(self):
        # AMG ENIs go at t=120 s, the CloudFront ENI gate clears at t=240 s.
        ec2, out = _run(amg_eni_gone_at=120, cf_eni_gone_at=240)
        self.assertEqual(ec2.sgs, {}, msg=f"SG left in the IDE VPC\n{out}\n{ec2.delete_attempts}")

    def test_sg_released_after_the_eni_gate_is_retried(self):
        # The AMG ENIs outlive the gate (t=60 s) by two minutes.
        ec2, out = _run(amg_eni_gone_at=180, cf_eni_gone_at=60)
        self.assertEqual(ec2.sgs, {}, msg=f"SG left in the IDE VPC\n{out}\n{ec2.delete_attempts}")
        self.assertIn("retrying", out)

    def test_sg_retry_is_bounded(self):
        ec2, out = _run(amg_eni_gone_at=10_000, cf_eni_gone_at=0)
        self.assertEqual(list(ec2.sgs), ["sg-amg"])
        self.assertLessEqual(len(ec2.delete_attempts), 20, ec2.delete_attempts)


if __name__ == "__main__":
    unittest.main()
