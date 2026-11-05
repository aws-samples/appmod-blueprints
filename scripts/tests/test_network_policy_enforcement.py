"""NetworkPolicy enforcement is part of the cluster contract (issue #1239).

- The `network-policy-enforcement` chart renders ONE object: kube-system/amazon-vpc-cni
  with enable-network-policy-controller "true" (EKS Auto Mode switch), applied with
  ServerSideApply (Argo CD owns that one field only) and never deleted/pruned.
- It ships no NetworkPolicy (no allow-all) and no enforcing-mode / strict setting.
- The registry entry selects every platform cluster (environment label present)
  unless the cluster secret explicitly sets enable_network_policy_enforcement=false.
- The appset-chart renders that ApplicationSet from the base registry, no overlay.
- Single value on clusters that also manage a vpc-cni EKS add-on: the karpenter
  chart (manageAddons) and the platform-cluster Composition both set
  enableNetworkPolicy "true", the same value the ConfigMap carries.

Run:  python -m pytest scripts/tests/test_network_policy_enforcement.py -q
"""
import json
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "network-policy-enforcement")
KARPENTER = os.path.join(REPO, "gitops", "addons", "charts", "karpenter")
REG = os.path.join(REPO, "gitops", "addons", "registry")
APPSET = os.path.join(REPO, "platform-charts", "appset-chart")
COMPOSITION = os.path.join(REPO, "gitops", "abstractions", "crossplane", "platform-cluster",
                           "templates", "composition.yaml")
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")


def helm_template(*args):
    r = subprocess.run([HELM, "template", *args], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def load(p):
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@needs_helm
def test_chart_renders_only_the_auto_mode_switch():
    docs = helm_template("network-policy-enforcement", CHART, "--namespace", "kube-system")
    assert len(docs) == 1
    cm = docs[0]
    assert (cm["kind"], cm["metadata"]["name"], cm["metadata"]["namespace"]) == (
        "ConfigMap", "amazon-vpc-cni", "kube-system")
    assert cm["data"] == {"enable-network-policy-controller": "true"}
    opts = set(cm["metadata"]["annotations"]["argocd.argoproj.io/sync-options"].split(","))
    assert opts == {"ServerSideApply=true", "Prune=false", "Delete=false"}


@needs_helm
def test_chart_ships_no_policy_and_no_enforcing_mode():
    docs = helm_template("network-policy-enforcement", CHART, "--namespace", "kube-system")
    assert not [d for d in docs if "NetworkPolicy" in d.get("kind", "")]
    rendered = yaml.safe_dump_all(docs)
    assert not re.search(r"ENFORCING_MODE|enforcingMode|DefaultDeny|strict", rendered, re.I)


def test_registry_entry_is_on_by_default_with_explicit_opt_out():
    e = load(os.path.join(REG, "core.yaml"))["network-policy-enforcement"]
    assert e["namespace"] == "kube-system"
    assert e["path"].endswith("addons/charts/network-policy-enforcement")
    assert e["selector"] == {"matchExpressions": [
        {"key": "environment", "operator": "Exists"},
        {"key": "enable_network_policy_enforcement", "operator": "NotIn", "values": ["false"]}]}
    assert "valuesObject" not in e  # nothing per cluster: no cluster names, no knobs


@needs_helm
def test_appset_rendered_from_base_registry():
    args = ["cluster-addons", APPSET, "-f", os.path.join(APPSET, "values.yaml")]
    for n in ("_defaults", "core", "gitops", "security", "observability", "platform", "ml"):
        args += ["-f", os.path.join(REG, n + ".yaml")]
    sets = [d for d in helm_template(*args)
            if d.get("kind") == "ApplicationSet" and d["metadata"]["name"] == "network-policy-enforcement"]
    assert len(sets) == 1
    s = sets[0]
    sel = s["spec"]["generators"][0]["clusters"]["selector"]
    assert sel["matchLabels"] == {"argocd.argoproj.io/secret-type": "cluster"}
    assert sel["matchExpressions"][1]["operator"] == "NotIn"
    tpl = s["spec"]["template"]
    assert tpl["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "-1"
    assert tpl["spec"]["destination"] == {"namespace": "kube-system", "name": "{{ .name }}"}
    # the cluster generator deploys to EVERY selected cluster itself (hub and spokes)
    assert "valuesObject" not in tpl["spec"]["sources"][1]["helm"]


def _addon_config(docs, addon):
    for d in docs:
        if d.get("kind") == "Addon" and d["spec"]["forProvider"]["addonName"] == addon:
            return json.loads(d["spec"]["forProvider"]["configurationValues"])
    pytest.fail(f"no {addon} Addon rendered")


@needs_helm
def test_karpenter_vpc_cni_addon_keeps_the_same_value(tmp_path):
    # Render the wrapper's own templates without fetching the upstream subchart.
    chart = tmp_path / "karpenter"
    shutil.copytree(KARPENTER, chart, ignore=shutil.ignore_patterns("charts", "Chart.lock"))
    meta = load(chart / "Chart.yaml")
    meta.pop("dependencies", None)
    (chart / "Chart.yaml").write_text(yaml.safe_dump(meta))
    base = [str(chart), "--set", "aws.clusterName=c1", "--set", "aws.region=r1",
            "--set", "aws.accountId=000000000000", "--set", "node.manageAddons=true",
            "--show-only", "templates/eks-addons.yaml"]
    assert _addon_config(helm_template("k", *base), "vpc-cni") == {"enableNetworkPolicy": "true"}
    # absent by default (manageAddons=false): no second vpc-cni owner on spokes
    out = subprocess.run([HELM, "template", "k", str(chart), "--set", "aws.clusterName=c1",
                          "--set", "aws.region=r1", "--set", "aws.accountId=000000000000",
                          "--show-only", "templates/eks-addons.yaml"], capture_output=True, text=True)
    assert out.returncode != 0 and "could not find template" in out.stderr


def test_platform_cluster_composition_vpc_cni_enforces():
    with open(COMPOSITION, encoding="utf-8") as fh:
        text = fh.read()
    block = text[text.index("- name: addon-vpc-cni"):text.index("- name: addon-kube-proxy")]
    raw = re.search(r"configurationValues: \|\n\s+(\{.*\})", block).group(1)
    assert json.loads(raw) == {"tolerations": [{"operator": "Exists"}], "enableNetworkPolicy": "true"}
