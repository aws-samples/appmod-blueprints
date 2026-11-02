"""Hermetic tests for the argocd-status-mcp filter (workshop/aiops-agent/src/argocd-status-mcp).

Fixture Applications cover every non-green state seen on a live hub (Unknown sync,
OutOfSync, Degraded, Progressing, Missing, no status at all) plus the all-Healthy
case. No cluster, no network.

Run:  python -m pytest workshop/scripts/tests/test_aiops_argocd_status_filter.py -q
"""
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "workshop", "aiops-agent", "src", "argocd-status-mcp"))

import status  # noqa: E402


def app(name, sync="Synced", health="Healthy", cluster="hub", addon=None, phase=None,
        conditions=None, health_msg=None, with_status=True):
    labels = {"clusterName": cluster}
    if addon:
        labels.update({"addon": "true", "addonName": addon})
    a = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": name, "namespace": "argocd", "labels": labels},
        "spec": {"destination": {"name": cluster, "namespace": "default"}},
    }
    if with_status:
        st = {"sync": {"status": sync}, "health": {"status": health}}
        if health_msg:
            st["health"]["message"] = health_msg
        if phase:
            st["operationState"] = {"phase": phase}
        if conditions:
            st["conditions"] = conditions
        a["status"] = st
    return a


FLEET = [
    app("a-green", cluster="hub", addon="metrics-server"),
    app("b-unknown", sync="Unknown", cluster="spoke-staging", addon="kyverno",
        conditions=[{"type": "ComparisonError", "message": "cluster not found " + "x" * 400}]),
    app("c-outofsync", sync="OutOfSync", health="Healthy", cluster="spoke-dev"),
    app("d-degraded", sync="OutOfSync", health="Degraded", cluster="spoke-dev",
        phase="Failed", health_msg="Deployment exceeded its progress deadline"),
    app("e-progressing", sync="Synced", health="Progressing", cluster="hub", phase="Running"),
    app("f-missing", sync="OutOfSync", health="Missing", cluster="spoke-prod", addon="kyverno"),
    app("g-nostatus", with_status=False, cluster="hub"),
    app("h-green", cluster="spoke-prod"),
]


def names(result):
    return [r["name"] for r in result["applications"]]


def test_returns_only_not_synced_and_healthy_with_totals():
    r = status.summarize(FLEET)
    assert r["total"] == 8
    assert r["unhealthy"] == 6
    assert set(names(r)) == {"b-unknown", "c-outofsync", "d-degraded", "e-progressing",
                             "f-missing", "g-nostatus"}
    assert r["truncated"] == 0


def test_unknown_sync_is_reported_not_hidden():
    r = status.summarize([app("x", sync="Unknown", health="Healthy")])
    assert r["unhealthy"] == 1 and r["applications"][0]["sync"] == "Unknown"


def test_missing_status_counts_as_unknown():
    row = status.summarize([app("x", with_status=False)])["applications"][0]
    assert row["sync"] == "Unknown" and row["health"] == "Unknown"


def test_all_healthy_returns_empty_list_but_full_total():
    r = status.summarize([app("a"), app("b"), app("c")])
    assert r == {"total": 3, "unhealthy": 0, "by_state": {}, "filters": {},
                 "applications": [], "truncated": 0}


def test_row_is_compact_and_message_truncated():
    row = [x for x in status.summarize(FLEET)["applications"] if x["name"] == "b-unknown"][0]
    assert set(row) == {"name", "cluster", "sync", "health", "operation", "message"}
    assert len(row["message"]) <= status.MESSAGE_MAX
    assert row["message"].startswith("cluster not found")
    assert row["cluster"] == "spoke-staging"


def test_operation_phase_and_health_message_fallback():
    row = [x for x in status.summarize(FLEET)["applications"] if x["name"] == "d-degraded"][0]
    assert row["operation"] == "Failed"
    assert row["message"] == "Deployment exceeded its progress deadline"


def test_cluster_filter_matches_destination_or_label_and_scopes_total():
    r = status.summarize(FLEET, cluster="spoke-dev")
    assert r["total"] == 2 and names(r) == ["c-outofsync", "d-degraded"]
    assert r["filters"] == {"cluster": "spoke-dev"}


def test_addon_filter():
    r = status.summarize(FLEET, addon="kyverno")
    # rows are sorted by (cluster, name): spoke-prod before spoke-staging
    assert r["total"] == 2 and names(r) == ["f-missing", "b-unknown"]


def test_by_state_counts():
    r = status.summarize(FLEET)
    assert r["by_state"]["OutOfSync/Degraded"] == 1
    assert r["by_state"]["Unknown/Unknown"] == 1
    assert sum(r["by_state"].values()) == r["unhealthy"]


def test_max_rows_truncates_but_keeps_counts():
    r = status.summarize(FLEET, max_rows=2)
    assert len(r["applications"]) == 2 and r["unhealthy"] == 6 and r["truncated"] == 4


def test_destination_server_used_when_no_name():
    a = app("srv", sync="OutOfSync")
    a["spec"]["destination"] = {"server": "https://kubernetes.default.svc"}
    assert status.summarize([a])["applications"][0]["cluster"] == "https://kubernetes.default.svc"


def test_output_is_small_compared_with_the_input():
    big = [app(f"app-{i}", conditions=[{"message": "m" * 5000}]) for i in range(150)]
    big += [app(f"bad-{i}", sync="Unknown", conditions=[{"message": "m" * 5000}]) for i in range(30)]
    out = json.dumps(status.summarize(big))
    assert len(out) < 0.02 * len(json.dumps(big))
