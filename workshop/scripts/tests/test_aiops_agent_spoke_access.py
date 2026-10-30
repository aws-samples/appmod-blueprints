"""`helm template` tests for the aiops-agent spoke AccessEntries.

Spoke access is no longer a hardcoded `<prefix>-spoke-dev/-prod` pair inside
chart/files/aiops-agent-app.yaml: the chart renders an ApplicationSet whose cluster
generator walks this hub's spoke cluster secrets, and each generated Application renders
workshop/aiops-agent/access-chart with the spoke's real aws_cluster_name.

ArgoCD is not available here, so the generator is emulated end to end:
  1. render the chart, take the ApplicationSet;
  2. evaluate its cluster selector against fake cluster secrets (Python);
  3. fill its Go template for each selected secret with `helm template` + `tpl` (Helm's
     sprig set is the one ArgoCD's goTemplate uses);
  4. render access-chart with the resulting values.

Run:  python -m pytest workshop/scripts/tests/test_aiops_agent_spoke_access.py -q
"""
import json
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "workshop", "aiops-agent", "chart")
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")

ACCOUNT = "111111111111"
REPO_URL = "https://git.example.com/platform/appmod-blueprints.git"


def _helm(*args):
    res = subprocess.run([HELM, *args], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return res.stdout


def _docs(text):
    return [d for d in yaml.safe_load_all(text) if d]


def _render_chart(prefix):
    return _docs(_helm("template", "aiops-agent", CHART, "--set", f"accountId={ACCOUNT}",
                       "--set", f"clusterPrefix={prefix}"))


def _by_kind(docs, kind):
    return [d for d in docs if d.get("kind") == kind]


def _secret(name, fleet_member):
    """An ArgoCD cluster secret as the fleet-secret chart / rg-eks writes it."""
    return {
        "name": name,
        "labels": {"argocd.argoproj.io/secret-type": "cluster", "fleet_member": fleet_member,
                   "aws_cluster_name": name},
        "annotations": {"aws_cluster_name": name, "addonsRepoURL": REPO_URL,
                        "addonsRepoRevision": "main"},
    }


def _selected(selector, labels):
    for k, v in (selector.get("matchLabels") or {}).items():
        if labels.get(k) != v:
            return False
    for e in selector.get("matchExpressions") or []:
        present, val = e["key"] in labels, labels.get(e["key"])
        op = e["operator"]
        if op == "In" and not (present and val in e["values"]):
            return False
        if op == "NotIn" and present and val in e["values"]:
            return False
        if op == "Exists" and not present:
            return False
        if op == "DoesNotExist" and present:
            return False
    return True


def _fill(template, secret, tmp_path):
    """Fill an ApplicationSet goTemplate for one cluster-generator element."""
    chart = tmp_path / "tplchart"
    (chart / "templates").mkdir(parents=True, exist_ok=True)
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: tpl\nversion: 0.1.0\n")
    (chart / "templates" / "out.yaml").write_text(
        '{{ tpl .Values.tmpl (dict "name" .Values.p.name "metadata" '
        '(dict "labels" .Values.p.labels "annotations" .Values.p.annotations)) }}\n')
    vals = tmp_path / "vals.json"
    vals.write_text(json.dumps({"tmpl": yaml.safe_dump(template), "p": secret}))
    return yaml.safe_load(_helm("template", "t", str(chart), "-f", str(vals)))


def _generate(prefix, secrets, tmp_path):
    """-> (hub OAM Application, [AccessEntry rendered on the hub for each spoke])."""
    docs = _render_chart(prefix)
    (app,) = _by_kind(docs, "Application")
    (appset,) = _by_kind(docs, "ApplicationSet")
    sel = appset["spec"]["generators"][0]["clusters"]["selector"]
    entries = []
    for s in secrets:
        if not _selected(sel, s["labels"]):
            continue
        gen = _fill(appset["spec"]["template"], s, tmp_path)
        assert gen["spec"]["destination"] == {"name": f"{prefix}-hub", "namespace": "aiops-agent"}
        src = gen["spec"]["source"]
        assert src["repoURL"] == REPO_URL and src["targetRevision"] == "main"
        vals = tmp_path / "access.json"
        vals.write_text(json.dumps(src["helm"]["valuesObject"]))
        out = _docs(_helm("template", src["helm"]["releaseName"],
                          os.path.join(REPO, src["path"]), "-f", str(vals)))
        entries += _by_kind(out, "AccessEntry")
    return app, entries


def _hub_entries(app):
    for comp in app["spec"]["components"]:
        if comp["name"] == "agent-access":
            return [o for o in comp["properties"]["objects"] if o["kind"] == "AccessEntry"]
    pytest.fail("no agent-access component rendered")


def _prompt(app):
    for comp in app["spec"]["components"]:
        msg = (comp.get("properties") or {}).get("systemMessage")
        if msg:
            return msg
    pytest.fail("no systemMessage rendered")


@needs_helm
def test_workshop_fleet_keeps_spoke_dev_and_prod(tmp_path):
    fleet = [_secret("peeks-hub", "control-plane"), _secret("peeks-spoke-dev", "spoke"),
             _secret("peeks-spoke-prod", "spoke")]
    app, spokes = _generate("peeks", fleet, tmp_path)
    assert [e["spec"]["clusterName"] for e in _hub_entries(app)] == ["peeks-hub"]
    assert sorted(e["spec"]["clusterName"] for e in spokes) == ["peeks-spoke-dev", "peeks-spoke-prod"]
    hub = _hub_entries(app)[0]["spec"]
    for e in spokes:
        assert e["metadata"]["namespace"] == "aiops-agent"
        # Same grant as the hub entry (and as the former inline spoke entries).
        assert {k: v for k, v in e["spec"].items() if k != "clusterName"} == \
               {k: v for k, v in hub.items() if k != "clusterName"}


@needs_helm
def test_non_workshop_single_spoke(tmp_path):
    fleet = [_secret("acme-hub", "control-plane"), _secret("acme-dev", "spoke")]
    app, spokes = _generate("acme", fleet, tmp_path)
    assert [e["spec"]["clusterName"] for e in _hub_entries(app)] == ["acme-hub"]
    assert [e["spec"]["clusterName"] for e in spokes] == ["acme-dev"]
    assert spokes[0]["spec"]["principalARN"] == f"arn:aws:iam::{ACCOUNT}:role/aiops-agent-role"


@needs_helm
def test_hub_without_spokes(tmp_path):
    app, spokes = _generate("acme", [_secret("acme-hub", "control-plane")], tmp_path)
    assert [e["spec"]["clusterName"] for e in _hub_entries(app)] == ["acme-hub"]
    assert spokes == []


@needs_helm
def test_no_hardcoded_spoke_names():
    docs = _render_chart("acme")
    (app,) = _by_kind(docs, "Application")
    text = yaml.safe_dump(app)
    assert "acme-spoke-dev" not in text and "acme-spoke-prod" not in text
    p = _prompt(app)
    env = p[p.index("# THIS ENVIRONMENT"):p.index("# GitOps remediation")]
    assert "`acme-hub`" in env
    assert "Discover them with eks-read" in env
    assert "spoke-prod" not in env


@needs_helm
def test_access_chart_requires_cluster_name():
    res = subprocess.run([HELM, "template", "x", os.path.join(REPO, "workshop", "aiops-agent",
                                                             "access-chart"),
                          "--set", f"accountId={ACCOUNT}"], capture_output=True, text=True)
    assert res.returncode != 0 and "clusterName is required" in res.stderr
