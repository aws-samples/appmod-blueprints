"""End-to-end orchestration harness for the split sweep (issue #924, principle #2).

Runs sweep.orchestrator.main() against FAKE boto3 clients (no AWS, no network, no
real sleeps) to guard the mechanical module split against regressions that static
checks miss: wrong section ordering, ctx-wiring bugs, NameErrors from the
relocation, and the residue/exit-code logic. The fakes model a "nothing exists"
account, so every reaper runs its empty-path and the run must reach DESTROY
COMPLETE (exit 0) without raising.

Design note (why no sleeps happen): describe_cluster / describe_repositories raise
the not-found exceptions, so the existence checks short-circuit BEFORE any
poll_until wait loop is entered — the whole harness runs instantly.
"""

import os
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ── Fake AWS not-found exceptions ────────────────────────────────────────────────
class _ResourceNotFound(Exception):
    pass


class _RepoNotFound(Exception):
    pass


class _Exceptions:
    ResourceNotFoundException = _ResourceNotFound
    RepositoryNotFoundException = _RepoNotFound


# Methods that must raise "not found" so existence checks short-circuit fast.
_RAISE = {
    ("eks", "describe_cluster"): _ResourceNotFound,
    ("ecr", "describe_repositories"): _RepoNotFound,
    ("ecr", "delete_repository"): _RepoNotFound,
}


class _R:
    """Empty AWS response: [] for any [key], and the given default for .get()."""

    def __getitem__(self, key):
        return []

    def get(self, key, default=None):
        return default


_EMPTY_RESP = _R()


class _Paginator:
    def paginate(self, *a, **k):
        return iter(())  # no pages → "nothing exists"


class FakeClient:
    def __init__(self, service):
        self._service = service
        self.exceptions = _Exceptions()

    def get_paginator(self, *a, **k):
        return _Paginator()

    def __getattr__(self, name):
        service = self.__dict__.get("_service")
        exc = _RAISE.get((service, name))
        if exc is not None:
            def _raise(*a, **k):
                raise exc(f"{service}.{name}: not found (fake)")
            return _raise

        def _call(*a, **k):
            return _EMPTY_RESP
        return _call


def _fake_client(service, **kwargs):
    return FakeClient(service)


# ── Fake Resource Groups Tagging API (peeks.io=<stack> gate) ──────────────────────
class _TagPaginator:
    def __init__(self, mappings):
        self._mappings = mappings

    def paginate(self, *a, **k):
        return iter([{"ResourceTagMappingList": self._mappings}])


class FakeTaggingClient(FakeClient):
    """resourcegroupstaggingapi whose get_resources paginator yields the given
    ResourceTagMappingList; every other call behaves like the empty FakeClient."""

    def __init__(self, mappings):
        super().__init__("resourcegroupstaggingapi")
        self._mappings = mappings

    def get_paginator(self, name):
        if name == "get_resources":
            return _TagPaginator(self._mappings)
        return _Paginator()


def _fake_client_with_tags(mappings):
    def factory(service, **kwargs):
        if service == "resourcegroupstaggingapi":
            return FakeTaggingClient(mappings)
        return FakeClient(service)

    return factory


class SweepOrchestrationTest(unittest.TestCase):
    def test_full_run_reaches_destroy_complete(self):
        # Patch the ONLY boto3.client call site (context.py) before importing main.
        with mock.patch("sweep.context.boto3.client", side_effect=_fake_client):
            from sweep.orchestrator import main
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main("us-west-2", "peeks")
            out = buf.getvalue()

        # Exit 0 == DESTROY COMPLETE (nothing exists in the fake account).
        self.assertEqual(rc, 0, msg=out)
        self.assertIn("DESTROY COMPLETE", out)
        self.assertIn("Extended sweep complete.", out)

    def test_all_sections_execute_in_order(self):
        """Every reaper ran (no NameError / no crash short-circuited the chain) and
        the hub EKS section ran before the final re-sweep."""
        with mock.patch("sweep.context.boto3.client", side_effect=_fake_client):
            from sweep.orchestrator import main
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main("us-west-2", "peeks")
            out = buf.getvalue()

        # A representative marker from each major section's empty-path.
        for marker in (
            "No EKS capabilities to delete",          # §1
            "No CloudFront distributions/VPC origins",  # §2
            "No ALBs to delete",                       # §3
            "No RDS instances to delete",              # §4
            "No AMP scrapers to delete",               # §5
            "Hub EKS cluster already gone",            # §6
            "No orphaned spoke clusters to delete",    # §6b
            "Deleted 0 IAM roles",                     # §7
            "force-deleted 0 secret",                  # §8
            "ECR: force-deleted 0",                    # §8b
            "No orphaned S3 buckets to delete",        # §8c
            "no matching log groups found",            # §9
            "No spoke VPCs to delete",                 # §10
            "No AMG workspaces to delete",             # §11
            "No CW Logs deliveries to delete",         # §12
            "No orphaned load balancers to delete",    # §12b
            "No orphaned EIPs to release",             # §13
            "No guardduty-data VPC endpoints",         # §13b
            "No orphan spoke/Crossplane VPCs to reap",  # §14
            "skipping leftover SG cleanup",            # §15
            "No GuardDuty-managed SGs to delete",      # §15b
            "skipping final re-sweep",                 # §16
            "no peeks.io stack tag",                   # §16b (final net inert w/o stack)
        ):
            self.assertIn(marker, out, msg=f"missing section marker: {marker!r}\n{out}")

    def test_residue_forces_nonzero_exit(self):
        """If verify reports residue, main() returns 1 (unless SWEEP_ALLOW_RESIDUE)."""
        with mock.patch("sweep.context.boto3.client", side_effect=_fake_client), \
             mock.patch("sweep.reapers.verify.run", return_value=["vpc:vpc-123"]):
            from sweep.orchestrator import main
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main("us-west-2", "peeks")
            self.assertEqual(rc, 1)

            os.environ["SWEEP_ALLOW_RESIDUE"] = "true"
            try:
                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2):
                    rc2 = main("us-west-2", "peeks")
                self.assertEqual(rc2, 0)
            finally:
                del os.environ["SWEEP_ALLOW_RESIDUE"]


class PeeksIoTagGateTest(unittest.TestCase):
    """Authoritative peeks.io=<stack> completeness gate (appmod-blueprints#924, §17d)."""

    def _run(self, mappings, stack_name="peeks-workshop-test"):
        with mock.patch("sweep.context.boto3.client", side_effect=_fake_client_with_tags(mappings)):
            from sweep.orchestrator import main
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main("us-west-2", "peeks", stack_name)
            return rc, buf.getvalue()

    def test_out_of_cfn_tagged_resource_is_residue(self):
        """A resource tagged peeks.io=<stack> WITHOUT aws:cloudformation:* tags is
        out-of-CFN (kro/ACK) residue -> non-zero exit."""
        arn = "arn:aws:eks:us-west-2:111122223333:cluster/oap-test"
        rc, out = self._run(
            [{"ResourceARN": arn, "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"}]}]
        )
        self.assertEqual(rc, 1, msg=out)
        self.assertIn(f"tagged:{arn}", out)

    def test_layer1_cfn_tagged_resource_is_excluded(self):
        """The IDE VPC (Layer 1) carries peeks.io AND aws:cloudformation:* -> excluded
        from the gate (CloudFormation deletes it after the sweep), so no false residue."""
        arn = "arn:aws:ec2:us-west-2:111122223333:vpc/vpc-ide"
        rc, out = self._run(
            [{"ResourceARN": arn, "Tags": [
                {"Key": "peeks.io", "Value": "peeks-workshop-test"},
                {"Key": "aws:cloudformation:stack-name", "Value": "peeks-workshop-test"},
            ]}]
        )
        self.assertEqual(rc, 0, msg=out)
        self.assertIn("DESTROY COMPLETE", out)
        self.assertNotIn("tagged:", out)

    def test_no_stack_name_skips_tag_gate(self):
        """Without a stack name, the tag gate is skipped even if the tagging API would
        return matches -> unchanged pre-tag behaviour."""
        arn = "arn:aws:eks:us-west-2:111122223333:cluster/oap-test"
        rc, out = self._run(
            [{"ResourceARN": arn, "Tags": [{"Key": "peeks.io", "Value": "x"}]}],
            stack_name=None,
        )
        self.assertEqual(rc, 0, msg=out)
        self.assertNotIn("tagged:", out)


class _AccessDenied(Exception):
    """botocore-shaped AccessDenied so resilience.classify() → 'access_denied'."""

    def __init__(self, msg="not authorized"):
        super().__init__(msg)
        self.response = {"Error": {"Code": "AccessDenied", "Message": msg}}


class RecordingClient(FakeClient):
    """FakeClient that RECORDS every method call into a shared list and can raise
    AccessDenied for named methods. When `live` is provided, a successful delete-ish
    call removes any tagged mapping whose ARN contains one of the call's string args
    (models deletion reflecting in the tagging API for the end-to-end pipeline test)."""

    def __init__(self, service, calls, deny=None, live=None):
        super().__init__(service)
        self._calls = calls
        self._deny = deny or set()
        self._live = live

    def __getattr__(self, name):
        service = self.__dict__.get("_service")

        def _call(*a, **k):
            self.__dict__["_calls"].append((service, name, k))
            if name in self.__dict__.get("_deny", set()):
                raise _AccessDenied(f"{service}.{name} not authorized")
            # Existence checks must raise not-found so the reapers short-circuit
            # (no real poll_until sleeps) and verify §17c does not false-positive.
            if name == "describe_repositories":
                raise _RepoNotFound(f"{service}.{name}: not found (fake)")
            if name == "describe_cluster":
                raise _ResourceNotFound(f"{service}.{name}: not found (fake)")
            live = self.__dict__.get("_live")
            if live is not None and (name.startswith("delete") or name == "release_address"):
                for v in k.values():
                    if isinstance(v, str):
                        live[:] = [m for m in live if v not in m["ResourceARN"]]
            return _EMPTY_RESP

        return _call


def _recording_factory(mappings, calls, deny=None, live=None):
    def factory(service, **kwargs):
        if service == "resourcegroupstaggingapi":
            return _StatefulTaggingClient(live) if live is not None else FakeTaggingClient(mappings)
        return RecordingClient(service, calls, deny, live)

    return factory


class _StatefulTaggingClient(FakeTaggingClient):
    """Tagging client whose get_resources reflects the CURRENT `live` list, so a
    resource the final net deletes disappears from the §17 gate's re-query."""

    def __init__(self, live):
        super().__init__(live)
        self._live = live

    def get_paginator(self, name):
        if name == "get_resources":
            return _TagPaginator(self._live)
        return _Paginator()


class FinalNetReaperTest(unittest.TestCase):
    """§16b tag-driven final net: deletes out-of-CFN peeks.io orphans, skips Layer 1,
    leaves unhandled/denied for the §17 gate (appmod-blueprints#924)."""

    def _ctx(self, mappings, deny=None, live=None):
        calls = []
        with mock.patch("sweep.context.boto3.client",
                        side_effect=_recording_factory(mappings, calls, deny, live)):
            from sweep.context import SweepContext
            ctx = SweepContext("us-west-2", "peeks", "peeks-workshop-test")
        return ctx, calls

    def _run(self, ctx):
        import io
        import contextlib
        from sweep.reapers import finalnet

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = finalnet.run(ctx)
        return summary, buf.getvalue()

    def test_deletes_orphans_skips_layer1_leaves_unhandled(self):
        mappings = [
            {"ResourceARN": "arn:aws:s3:::peeks-ray-models-123",
             "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"}]},
            {"ResourceARN": "arn:aws:ecr:us-west-2:111122223333:repository/peeks-ray-vllm-custom",
             "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"}]},
            {"ResourceARN": "arn:aws:eks:us-west-2:111122223333:cluster/oap-test",
             "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"}]},
            # Layer 1 CFN-managed → MUST be skipped (CloudFormation reaps it)
            {"ResourceARN": "arn:aws:ec2:us-west-2:111122223333:vpc/vpc-ide",
             "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"},
                      {"Key": "aws:cloudformation:stack-name", "Value": "peeks-workshop-test"}]},
            # unhandled service type → left for the §17 gate, never blind-deleted
            {"ResourceARN": "arn:aws:dynamodb:us-west-2:111122223333:table/oap-state",
             "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"}]},
        ]
        ctx, calls = self._ctx(mappings)
        summary, out = self._run(ctx)

        self.assertEqual(summary["deleted"], 3, msg=out)      # s3 + ecr + eks
        self.assertEqual(summary["skipped_cfn"], 1, msg=out)  # vpc-ide (Layer 1)
        self.assertEqual(summary["unhandled"], 1, msg=out)    # dynamodb table
        self.assertEqual(summary["access_denied"], 0, msg=out)
        methods = {(s, m) for s, m, _k in calls}
        self.assertIn(("s3", "delete_bucket"), methods)
        self.assertIn(("ecr", "delete_repository"), methods)
        self.assertIn(("eks", "delete_cluster"), methods)
        # The CFN-managed IDE VPC must NEVER be touched by the net.
        self.assertNotIn(("ec2", "delete_vpc"), methods)
        self.assertIn("unhandled tagged resource", out)

    def test_access_denied_surfaced_not_counted_deleted(self):
        mappings = [
            {"ResourceARN": "arn:aws:ecr:us-west-2:111122223333:repository/peeks-ray-vllm-custom",
             "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"}]},
        ]
        ctx, _calls = self._ctx(mappings, deny={"delete_repository"})
        summary, out = self._run(ctx)
        self.assertEqual(summary["access_denied"], 1, msg=out)
        self.assertEqual(summary["deleted"], 0, msg=out)
        self.assertIn("ACCESS DENIED", out)

    def test_inert_without_stack_name(self):
        calls = []
        with mock.patch("sweep.context.boto3.client",
                        side_effect=_recording_factory([], calls)):
            from sweep.context import SweepContext
            ctx = SweepContext("us-west-2", "peeks", None)
        summary, out = self._run(ctx)
        self.assertEqual(summary, {"deleted": 0, "skipped_cfn": 0, "access_denied": 0,
                                   "unhandled": 0, "failed": 0})
        self.assertIn("no peeks.io stack tag", out)

    def test_end_to_end_net_deletes_then_gate_is_clean(self):
        """Pipeline: net deletes the tagged orphans → §17 gate re-queries live → 0
        residue → main() exits 0. Uses a stateful tagging fake so a deleted resource
        disappears from the gate's enumeration."""
        live = [
            {"ResourceARN": "arn:aws:s3:::peeks-ray-models-123",
             "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"}]},
            {"ResourceARN": "arn:aws:ecr:us-west-2:111122223333:repository/peeks-ray-vllm-custom",
             "Tags": [{"Key": "peeks.io", "Value": "peeks-workshop-test"}]},
        ]
        calls = []
        with mock.patch("sweep.context.boto3.client",
                        side_effect=_recording_factory(None, calls, live=live)):
            from sweep.orchestrator import main
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main("us-west-2", "peeks", "peeks-workshop-test")
            out = buf.getvalue()

        self.assertEqual(rc, 0, msg=out)               # net cleared the orphans
        self.assertIn("DESTROY COMPLETE", out)
        self.assertNotIn("tagged:arn:aws:s3", out)     # gate saw them gone
        self.assertEqual(live, [], msg=f"live not emptied: {live}")


if __name__ == "__main__":
    unittest.main()
