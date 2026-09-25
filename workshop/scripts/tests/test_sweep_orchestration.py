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


if __name__ == "__main__":
    unittest.main()
