"""Hermetic test: the CloudFront reapers (§2 and re-sweep §16d) wait for a disabled
distribution to be Deployed (up to ~20 min) before deleting it, and still delete the VPC origin.

Live case: after update_distribution(Enabled=False) the distribution stayed InProgress for more
than the old 300 s poll; the poll result was ignored, delete_distribution failed with
DistributionNotDisabled, and the VPC-origin delete was skipped, so its ENIs blocked the IDE
subnets (stack DELETE_FAILED). A distribution that was already Enabled=False skipped the wait.

Virtual clock, no AWS, no real sleep.
Run:  python -m pytest workshop/scripts/tests/test_sweep_cloudfront_disable_wait.py -q
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_sweep_orchestration as orch  # noqa: E402  (puts the sweep dir on sys.path)

DIST = "EDIST1"
VO = "vo-1"


class _Err(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class FakeCf(orch.FakeClient):
    """Disable takes `deploy_after` s on the virtual clock; delete before that is refused."""

    def __init__(self, clock, enabled, deploy_after, deployed_at_start=False):
        super().__init__("cloudfront")
        self.clock = clock
        self.enabled = enabled
        self.deploy_after = deploy_after
        self.deployed_at = 0 if deployed_at_start else None
        self.deleted = False
        self.vo_deleted = False
        self.delete_calls = 0

    def _deployed(self):
        return self.deployed_at is not None and self.clock["t"] >= self.deployed_at

    def list_vpc_origins(self):
        return {"VpcOriginList": {"Items": [{"Id": VO, "Name": "peeks-hub-vo"}]}}

    def list_distributions(self):
        return {"DistributionList": {"Items": [{"Id": DIST, "Comment": "peeks-hub-platform"}]}}

    def get_distribution_config(self, Id):
        return {"ETag": "e1", "DistributionConfig": {"Enabled": self.enabled}}

    def update_distribution(self, Id, DistributionConfig, IfMatch):
        self.enabled = DistributionConfig["Enabled"]
        self.deployed_at = self.clock["t"] + self.deploy_after

    def get_distribution(self, Id):
        return {"ETag": "e2", "Distribution": {"Status": "Deployed" if self._deployed() else "InProgress"}}

    def delete_distribution(self, Id, IfMatch):
        self.delete_calls += 1
        if self.enabled or not self._deployed():
            raise _Err("DistributionNotDisabled")
        self.deleted = True

    def get_vpc_origin(self, Id):
        return {"ETag": "e3"}

    def delete_vpc_origin(self, Id, IfMatch):
        if not self.deleted:
            raise _Err("CannotDeleteEntityWhileInUse")
        self.vo_deleted = True


def _ctx(cf):
    with mock.patch("sweep.context.boto3.client", side_effect=orch._fake_client):
        from sweep.context import SweepContext
        ctx = SweepContext("us-west-2", "peeks")
    ctx.cf = cf
    return ctx


def _run(which, enabled, deploy_after, deployed_at_start=False):
    clock = {"t": 0.0}
    return _run_with(FakeCf(clock, enabled, deploy_after, deployed_at_start), clock, which)


class CloudfrontDisableWaitTest(unittest.TestCase):
    def _check(self, which, enabled, deploy_after, deployed_at_start=False):
        cf, out = _run(which, enabled, deploy_after, deployed_at_start)
        self.assertTrue(cf.deleted, msg=out)
        self.assertTrue(cf.vo_deleted, msg=out)
        return cf

    def test_reap_slow_disable_over_old_300s_budget(self):
        cf = self._check("reap", enabled=True, deploy_after=600)
        self.assertEqual(cf.delete_calls, 1)

    def test_reap_already_disabled_still_in_progress(self):
        # disabled earlier, deploy finishes 600 s from now
        clock = {"t": 0.0}
        cf = FakeCf(clock, enabled=False, deploy_after=0)
        cf.deployed_at = 600
        self.assertFalse(cf._deployed())
        out_cf, out = _run_with(cf, clock, "reap")
        self.assertTrue(out_cf.deleted and out_cf.vo_deleted, msg=out)
        self.assertEqual(out_cf.delete_calls, 1, msg=out)

    def test_resweep_slow_disable_over_old_450s_budget(self):
        self._check("resweep", enabled=True, deploy_after=900)

    def test_resweep_already_disabled_still_in_progress(self):
        clock = {"t": 0.0}
        cf = FakeCf(clock, enabled=False, deploy_after=0)
        cf.deployed_at = 600
        out_cf, out = _run_with(cf, clock, "resweep")
        self.assertTrue(out_cf.deleted and out_cf.vo_deleted, msg=out)
        self.assertEqual(out_cf.delete_calls, 1, msg=out)

    def test_not_disabled_error_is_retried(self):
        clock = {"t": 0.0}
        cf = FakeCf(clock, enabled=False, deploy_after=0, deployed_at_start=True)
        real_delete = cf.delete_distribution
        state = {"n": 0}

        def flaky(Id, IfMatch):
            state["n"] += 1
            if state["n"] == 1:
                raise _Err("DistributionNotDisabled")
            real_delete(Id, IfMatch)
        cf.delete_distribution = flaky
        out_cf, out = _run_with(cf, clock, "reap")
        self.assertEqual(state["n"], 2, msg=out)
        self.assertTrue(out_cf.deleted and out_cf.vo_deleted, msg=out)

    def test_wait_is_bounded_and_vpc_origin_still_attempted(self):
        cf, out = _run("reap", enabled=True, deploy_after=10_000)
        self.assertFalse(cf.deleted)
        self.assertLessEqual(cf.delete_calls, 3)
        self.assertIn("not deleted", out)
        self.assertIn("CannotDeleteEntityWhileInUse", out)  # VPC origin delete was still attempted
        self.assertLessEqual(clock_of(cf), 1200 + 2 * 8 * 15 + 60)  # bounded: ~24 min

    def test_throttled_poll_does_not_end_the_wait(self):
        clock = {"t": 0.0}
        cf = FakeCf(clock, enabled=True, deploy_after=600)
        real_get = cf.get_distribution
        n = {"i": 0}

        def flaky(Id):
            n["i"] += 1
            if n["i"] == 2:
                raise _Err("Throttling")
            return real_get(Id)
        cf.get_distribution = flaky
        out_cf, out = _run_with(cf, clock, "reap")
        self.assertEqual(out_cf.delete_calls, 1, msg=out)
        self.assertTrue(out_cf.deleted and out_cf.vo_deleted, msg=out)


def clock_of(cf):
    return cf.clock["t"]


def _run_with(cf, clock, which):
    ctx = _ctx(cf)
    from sweep import resilience
    from sweep.reapers import cloudfront, resweep
    real = resilience.poll_until

    def virtual_poll(pred, *, attempts, delay, backoff=1.0, sleep=None):
        return real(pred, attempts=attempts, delay=delay, backoff=backoff,
                    sleep=lambda s: clock.__setitem__("t", clock["t"] + s))

    buf = io.StringIO()
    with mock.patch.object(cloudfront, "poll_until", virtual_poll), \
         mock.patch.object(resweep, "poll_until", virtual_poll), \
         mock.patch("time.sleep", lambda s: clock.__setitem__("t", clock["t"] + s)), \
         contextlib.redirect_stdout(buf):
        (cloudfront.reap if which == "reap" else resweep.run)(ctx)
    return cf, buf.getvalue()


if __name__ == "__main__":
    unittest.main()
