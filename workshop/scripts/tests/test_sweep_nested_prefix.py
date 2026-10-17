"""Hermetic tests: a stack's sweep leaves alone a stack whose prefix only STARTS with its own
(#1111).

Two workshop stacks share one account/region: "tdv" and "tdv2". The Secrets Manager name
filter and the CloudWatch Logs logGroupNamePrefix are bare string-prefix matches, so "tdv"
also lists every "tdv2" name; and AMP/AMG/log-delivery names were matched with a bare
startswith(prefix). A name is this stack's only when it is the prefix itself or starts
with "<prefix>-" or "<prefix>/" (the shapes the stack creates: <prefix>-hub/config,
<prefix>/platform/amp, /aws/eks/<prefix>-hub/cluster, <prefix>-hub-kro), and the same
rule applies to an arbitrarily named spoke.

The fake clients below answer list/describe calls from one fixture with the real APIs'
filter semantics and record every other call. No boto3 client, no network, no sleeping.

Run:  python -m pytest workshop/scripts/tests/test_sweep_nested_prefix.py -q
"""
import contextlib
import io
import os
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sweep.context import SweepContext  # noqa: E402
from sweep.reapers import amp as amp_reaper  # noqa: E402
from sweep.reapers import grafana as grafana_reaper  # noqa: E402
from sweep.reapers import logs as logs_reaper  # noqa: E402
from sweep.reapers import secrets as secrets_reaper  # noqa: E402
from sweep.reapers import verify as verify_reaper  # noqa: E402

PFX_TAG = "platform.gitops.io/prefix"

# ── Fixture: what the two stacks create (names from the Taskfiles / a live account) ──
TDV = {
    "secrets": ["tdv-hub/config", "tdv-hub/keycloak", "tdv-hub/keycloak-clients", "tdv-hub/secrets",
                "tdv-spoke-dev/config", "tdv-spoke-prod/config", "tdv-devlake/mysql-connection",
                "tdv/platform/amp", "tdv"],
    "amp": ["tdv-observability-amp", "tdv"],
    "grafana": ["tdv-observability"],
    "log_groups": ["/aws/eks/tdv-hub/cluster", "/aws/eks/tdv-hub/capability/kro",
                   "/aws/eks/tdv-spoke-dev/cluster", "/aws/eks/tdv-spoke-prod/cluster",
                   "/aws/eks/tdv/cluster", "/aws/containerinsights/tdv-hub/application",
                   "/aws/lambda/tdv-workshop-GitTokenSeedFn07B8F032-AbC"],
    "delivery_sources": ["tdv-hub-kro"],
    "delivery_destinations": ["tdv-hub-kro-cwl"],
}
TDV2 = {
    "secrets": ["tdv2-hub/config", "tdv2-hub/keycloak", "tdv2-hub/keycloak-clients", "tdv2-hub/secrets",
                "tdv2-spoke-dev/config", "tdv2-spoke-prod/config", "tdv2-devlake/mysql-connection",
                "tdv2/platform/amp"],
    "amp": ["tdv2-observability-amp"],
    "grafana": ["tdv2-observability"],
    "log_groups": ["/aws/eks/tdv2-hub/cluster", "/aws/eks/tdv2-hub/capability/kro",
                   "/aws/eks/tdv2-spoke-dev/cluster", "/aws/eks/tdv2-spoke-prod/cluster",
                   "/aws/containerinsights/tdv2-hub/performance",
                   "/aws/lambda/tdv2-workshop-GitTokenSeedFn07B8F032-XyZ"],
    "delivery_sources": ["tdv2-hub-kro"],
    "delivery_destinations": ["tdv2-hub-kro-cwl"],
}
# Names that share the "tdv" characters with no delimiter: never the tdv stack's.
OTHER = {
    "secrets": ["tdvfoo/config"],
    "amp": ["tdvx-observability-amp"],
    "grafana": ["tdvx"],
    "log_groups": ["/aws/eks/tdvx-hub/cluster"],
    "delivery_sources": [],
    "delivery_destinations": [],
}


def _account(*stacks, clusters=None):
    acct = {k: [n for s in stacks for n in s[k]] for k in TDV}
    acct["clusters"] = clusters or {}  # name -> tags; {} = every cluster already deleted
    return acct


ACCOUNT = _account(TDV, TDV2, OTHER)


class _NotFound(Exception):
    pass


class _Empty:
    """Empty AWS response: [] for any [key], the default for .get()."""

    def __getitem__(self, key):
        return []

    def get(self, key, default=None):
        return default


class _Pages:
    def __init__(self, pages):
        self._pages = pages  # callable(**paginate kwargs) -> list of pages

    def paginate(self, **k):
        return iter(self._pages(**k))


def _secret_arn(name):
    return f"arn:aws:secretsmanager:us-west-2:111122223333:secret:{name}-AbCdEf"


class _Client:
    """Fake boto3 client over an account fixture. Reads use the real filter semantics;
    every other call is recorded as (service, method, kwargs) and returns {}."""

    def __init__(self, service, account, calls):
        self._s, self._a, self._calls = service, account, calls
        self.exceptions = types.SimpleNamespace(ResourceNotFoundException=_NotFound,
                                                RepositoryNotFoundException=_NotFound)

    def get_paginator(self, op):
        a = self._a
        if (self._s, op) == ("secretsmanager", "list_secrets"):
            def pages(Filters=(), **k):
                # The real "name" filter is a case-insensitive PREFIX match.
                vals = tuple(v.lower() for f in Filters if f["Key"] == "name" for v in f["Values"])
                return [{"SecretList": [{"Name": n, "ARN": _secret_arn(n)}
                                        for n in a["secrets"] if n.lower().startswith(vals)]}]
            return _Pages(pages)
        if (self._s, op) == ("logs", "describe_log_groups"):
            return _Pages(lambda logGroupNamePrefix, **k: [{"logGroups": [
                {"logGroupName": n} for n in a["log_groups"] if n.startswith(logGroupNamePrefix)]}])
        if (self._s, op) == ("eks", "list_clusters"):
            return _Pages(lambda **k: [{"clusters": list(a["clusters"])}])
        return _Pages(lambda **k: [])

    def describe_cluster(self, name):
        if name not in self._a["clusters"]:
            raise _NotFound(name)
        return {"cluster": {"tags": self._a["clusters"][name], "status": "ACTIVE"}}

    def list_workspaces(self, **k):
        if self._s == "amp":
            return {"workspaces": [{"workspaceId": f"ws-{n}", "alias": n} for n in self._a["amp"]]}
        return {"workspaces": [{"id": f"g-{n}", "name": n} for n in self._a["grafana"]]}

    def list_scrapers(self, **k):
        return {"scrapers": []}

    def describe_delivery_sources(self, **k):
        return {"deliverySources": [{"name": n} for n in self._a["delivery_sources"]]}

    def describe_deliveries(self, **k):
        return {"deliveries": [{"id": f"d-{n}", "deliverySourceName": n} for n in self._a["delivery_sources"]]}

    def describe_delivery_destinations(self, **k):
        return {"deliveryDestinations": [{"name": n} for n in self._a["delivery_destinations"]]}

    def __getattr__(self, name):
        def _call(*a, **k):
            if not name.startswith(("describe_", "list_", "get_")):
                self._calls.append((self._s, name, k))
            return _Empty()
        return _call


def _factory(account, calls):
    return lambda service, **kw: _Client(service, account, calls)


def _ctx(prefix, account=ACCOUNT):
    calls = []
    with mock.patch("sweep.context.boto3.client", side_effect=_factory(account, calls)):
        ctx = SweepContext("us-west-2", prefix)
    ctx.log = lambda m: None
    return ctx, calls


def _name(method, k):
    """The resource name a recorded write targets (the fixture name, not the id/ARN)."""
    if method == "delete_secret":
        return k["SecretId"].split(":secret:", 1)[1][:-len("-AbCdEf")]
    if method == "delete_workspace":
        return k["workspaceId"].split("-", 1)[1]
    if method == "delete_delivery":
        return k["id"][len("d-"):]
    return k.get("logGroupName") or k.get("name") or k.get("repositoryName") or str(k)


def _targets(calls, method=None):
    """Sorted names targeted by the recorded writes (of `method`, or of every write)."""
    return sorted(_name(m, k) for _s, m, k in calls if method in (None, m))


def _all_names(*stacks):
    return {n for s in stacks for names in s.values() for n in names}


def test_secrets_reap_takes_only_this_stacks_secrets():
    ctx, calls = _ctx("tdv")
    secrets_reaper.reap(ctx)
    assert _targets(calls, "delete_secret") == sorted(TDV["secrets"])

    ctx, calls = _ctx("tdv2")
    secrets_reaper.reap(ctx)
    assert _targets(calls, "delete_secret") == sorted(TDV2["secrets"])


def test_amp_and_grafana_workspaces_take_only_this_stacks_names():
    ctx, calls = _ctx("tdv")
    amp_reaper.reap(ctx)
    grafana_reaper.reap(ctx)
    assert [c[0] for c in calls if c[1] == "delete_workspace"] == ["amp"] * 2 + ["grafana"]
    assert _targets(calls, "delete_workspace") == sorted(TDV["amp"] + TDV["grafana"])


def test_log_groups_take_only_this_stacks_groups():
    ctx, calls = _ctx("tdv")
    logs_reaper.reap_log_groups(ctx)
    assert _targets(calls, "delete_log_group") == sorted(TDV["log_groups"])

    ctx, calls = _ctx("tdv2")
    logs_reaper.reap_log_groups(ctx)
    assert _targets(calls, "delete_log_group") == sorted(TDV2["log_groups"])


def test_log_deliveries_take_only_this_stacks_objects():
    ctx, calls = _ctx("tdv")
    logs_reaper.reap_deliveries(ctx)
    assert _targets(calls, "delete_delivery") == ["tdv-hub-kro"]
    assert _targets(calls, "delete_delivery_source") == ["tdv-hub-kro"]
    assert _targets(calls, "delete_delivery_destination") == ["tdv-hub-kro-cwl"]


def test_verify_redrive_and_residue_take_only_this_stacks_names():
    ctx, calls = _ctx("tdv")
    residue = verify_reaper.run(ctx)
    # §17b re-drive deletes only this stack's /aws/eks log groups
    assert _targets(calls, "delete_log_group") == sorted(g for g in TDV["log_groups"] if g.startswith("/aws/eks/"))
    # §17c reports only this stack's secrets and log groups as residue
    assert sorted(r for r in residue if r.startswith(("secret:", "log-group:"))) == sorted(
        [f"secret:{n}" for n in TDV["secrets"]]
        + [f"log-group:{g}" for g in TDV["log_groups"] if g.startswith("/aws/eks/")])


def test_spoke_names_use_the_same_delimiter():
    # "team-a" is a tdv spoke (ownership tag); "team-ab" belongs to tdv2.
    clusters = {"team-a": {PFX_TAG: "tdv"}, "team-ab": {PFX_TAG: "tdv2"}}
    account = _account(TDV, clusters=clusters)
    account["secrets"] += ["team-a/config", "team-ab/config"]
    account["log_groups"] += ["/aws/eks/team-a/cluster", "/aws/containerinsights/team-a/application",
                              "/aws/eks/team-ab/cluster", "/aws/containerinsights/team-ab/application"]
    ctx, calls = _ctx("tdv", account)
    assert "team-a" in ctx.spokes and "team-ab" not in ctx.spokes
    secrets_reaper.reap(ctx)
    logs_reaper.reap_log_groups(ctx)
    assert _targets(calls, "delete_secret") == sorted(TDV["secrets"] + ["team-a/config"])
    assert _targets(calls, "delete_log_group") == sorted(
        TDV["log_groups"] + ["/aws/eks/team-a/cluster", "/aws/containerinsights/team-a/application"])


def _sweep(prefix):
    calls = []
    with mock.patch("sweep.context.boto3.client", side_effect=_factory(ACCOUNT, calls)):
        from sweep.orchestrator import main
        with contextlib.redirect_stdout(io.StringIO()):
            main("us-west-2", prefix)
    return calls


def test_full_sweep_never_writes_to_the_longer_prefix_stack():
    # The whole sweep, every reaper in order, for "tdv" after its clusters are gone.
    calls = _sweep("tdv")
    assert sorted(set(_targets(calls)) & _all_names(TDV2, OTHER)) == []
    # ...and it still takes every tdv secret / workspace / log group / delivery object.
    for method, expected in (("delete_secret", TDV["secrets"]),
                             ("delete_workspace", TDV["amp"] + TDV["grafana"]),
                             ("delete_delivery", TDV["delivery_sources"]),
                             ("delete_delivery_source", TDV["delivery_sources"]),
                             ("delete_delivery_destination", TDV["delivery_destinations"])):
        assert _targets(calls, method) == sorted(expected), method
    assert set(_targets(calls, "delete_log_group")) == set(TDV["log_groups"])


def test_full_sweep_of_the_longer_prefix_stack_unchanged():
    calls = _sweep("tdv2")
    assert sorted(set(_targets(calls)) & _all_names(TDV, OTHER)) == []
    assert _targets(calls, "delete_secret") == sorted(TDV2["secrets"])
    assert _targets(calls, "delete_workspace") == sorted(TDV2["amp"] + TDV2["grafana"])
    assert set(_targets(calls, "delete_log_group")) == set(TDV2["log_groups"])
