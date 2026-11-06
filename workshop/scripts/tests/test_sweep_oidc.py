"""Hermetic tests for the IAM OIDC provider reaper (§7b) and its §17 residue check.

Live case: the hub's OIDC provider (created by the hub's ACK capability, eks:* tags only,
no platform.gitops.io/prefix tag) stayed in the account after the stack delete, and the
gate still printed DESTROY COMPLETE. A provider is deleted only when an owner tag names one
of our clusters exactly, its URL is an EKS issuer of this region, and no EKS cluster still
present uses its issuer; if the region's clusters cannot be listed, nothing is deleted.

Run:  python -m pytest workshop/scripts/tests/test_sweep_oidc.py -q
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_sweep_orchestration as orch  # noqa: E402

REGION = "us-west-2"
ACCT = "111122223333"


def _url(i, region=REGION):
    return f"oidc.eks.{region}.amazonaws.com/id/{i}"


def _arn(i, region=REGION):
    return f"arn:aws:iam::{ACCT}:oidc-provider/{_url(i, region)}"


NS, RN, ACKNS, CAP = ("eks:kubernetes-namespace", "eks:kubernetes-resource-name",
                      "services.k8s.aws/namespace", "eks:eks-capability-arn")

PROVIDERS = {
    # ours, cluster gone -> deleted
    _arn("HUB"): {"Url": _url("HUB"), "Tags": [{"Key": NS, "Value": "peeks-hub"},
                                                {"Key": RN, "Value": "peeks-hub-oidc"}]},
    _arn("PROD"): {"Url": _url("PROD"), "Tags": [{"Key": ACKNS, "Value": "peeks-spoke-prod"}]},
    _arn("CAP"): {"Url": _url("CAP"), "Tags": [
        {"Key": CAP, "Value": f"arn:aws:eks:{REGION}:{ACCT}:capability/peeks-hub/ack/abc"}]},
    # ours by tag but its cluster is still there -> kept
    _arn("LIVE"): {"Url": _url("LIVE"), "Tags": [{"Key": NS, "Value": "peeks-spoke-dev"}]},
    # not ours -> kept
    _arn("OTHER"): {"Url": _url("OTHER"), "Tags": [{"Key": NS, "Value": "pvt-hub"}]},
    _arn("SUPER"): {"Url": _url("SUPER"), "Tags": [{"Key": NS, "Value": "peeks-hub2"}]},
    _arn("NOTAG"): {"Url": _url("NOTAG"), "Tags": []},
    _arn("REGION", "eu-west-3"): {"Url": _url("REGION", "eu-west-3"),
                                   "Tags": [{"Key": NS, "Value": "peeks-hub"}]},
    "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com":
        {"Url": "token.actions.githubusercontent.com", "Tags": []},
}
OURS = {_arn("HUB"), _arn("PROD"), _arn("CAP")}


class _ClusterPaginator:
    def __init__(self, names, fail):
        self.names, self.fail = names, fail

    def paginate(self, *a, **k):
        if self.fail:
            raise RuntimeError("eks:ListClusters AccessDenied")
        return iter([{"clusters": list(self.names)}])


class FakeEks(orch.FakeClient):
    def __init__(self, live, fail=False):
        super().__init__("eks")
        self.live, self.fail = live, fail

    def get_paginator(self, name):
        if name == "list_clusters":
            return _ClusterPaginator(self.live, self.fail)
        return orch._Paginator()

    def describe_cluster(self, name):
        return {"cluster": {"tags": {}, "identity": {"oidc": {"issuer": "https://" + _url(self.live[name])}}}}


class _Denied(Exception):
    def __init__(self):
        super().__init__("AccessDenied")
        self.response = {"Error": {"Code": "AccessDenied", "Message": "no"}}


class FakeIam(orch.FakeClient):
    def __init__(self, deny=False):
        super().__init__("iam")
        self.providers = dict(PROVIDERS)
        self.deny = deny
        self.deleted = []

    def list_open_id_connect_providers(self):
        return {"OpenIDConnectProviderList": [{"Arn": a} for a in self.providers]}

    def get_open_id_connect_provider(self, OpenIDConnectProviderArn):
        return self.providers[OpenIDConnectProviderArn]

    def delete_open_id_connect_provider(self, OpenIDConnectProviderArn):
        if self.deny:
            raise _Denied()
        self.deleted.append(OpenIDConnectProviderArn)
        self.providers.pop(OpenIDConnectProviderArn)


def _factory(iam, eks):
    def f(service, **kw):
        return {"iam": iam, "eks": eks}.get(service) or orch.FakeClient(service)
    return f


def _ctx(iam, eks):
    with mock.patch("sweep.context.boto3.client", side_effect=_factory(iam, eks)):
        from sweep.context import SweepContext
        return SweepContext(REGION, "peeks")


def _quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a)
    return r, buf.getvalue()


class OidcReaperTest(unittest.TestCase):
    def test_deletes_only_our_providers_of_gone_clusters(self):
        from sweep.reapers import oidc
        iam = FakeIam()
        eks = FakeEks({"peeks-spoke-dev": "LIVE", "pvt-hub": "OTHER"})
        ctx = _ctx(iam, eks)
        _r, out = _quiet(oidc.reap, ctx)
        self.assertEqual(set(iam.deleted), OURS, out)
        self.assertIn("OIDC providers: deleted 3", out)

    def test_fail_closed_when_clusters_cannot_be_listed(self):
        from sweep.reapers import oidc
        iam = FakeIam()
        ctx = _ctx(iam, FakeEks({}, fail=False))
        ctx.eks = FakeEks({}, fail=True)
        _r, out = _quiet(oidc.reap, ctx)
        self.assertEqual(iam.deleted, [], out)
        self.assertIn("none deleted", out)

    # The full runs use an empty region (a live cluster would send the cluster reapers into
    # their real waits), so the peeks-spoke-dev provider counts as ours and gone there.
    def test_gate_reports_undeleted_provider_as_residue(self):
        iam = FakeIam(deny=True)
        eks = FakeEks({})
        with mock.patch("sweep.context.boto3.client", side_effect=_factory(iam, eks)), \
             mock.patch("time.sleep", lambda s: None):
            from sweep.orchestrator import main
            rc, out = _quiet(main, REGION, "peeks")
        self.assertEqual(rc, 1, out)
        self.assertIn("ACCESS DENIED deleting OIDC provider HUB", out)
        for i in ("HUB", "PROD", "CAP", "LIVE"):
            self.assertIn(f"oidc-provider:{i}", out)
        for i in ("OTHER", "SUPER", "NOTAG", "REGION"):
            self.assertNotIn(f"oidc-provider:{i}", out)

    def test_full_run_clean_after_reap(self):
        iam = FakeIam()
        eks = FakeEks({})
        with mock.patch("sweep.context.boto3.client", side_effect=_factory(iam, eks)), \
             mock.patch("time.sleep", lambda s: None):
            from sweep.orchestrator import main
            rc, out = _quiet(main, REGION, "peeks")
        self.assertEqual(set(iam.deleted), OURS | {_arn("LIVE")}, out)
        self.assertNotIn("oidc-provider:", out)
        self.assertIn("DESTROY COMPLETE", out)


if __name__ == "__main__":
    unittest.main()
