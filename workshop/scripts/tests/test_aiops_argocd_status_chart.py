"""Hermetic `helm template` tests for the argocd-status-mcp component of the aiops-agent chart.

Off (images.argocdStatusMcp.tag empty, the default): nothing rendered, the agent's
mcpServers (= the OAP /ready set) and dependsOn are unchanged, and the prompt keeps the
prompt-only per-Application sweep rule (#1230). On (tag set): the component with its own
ServiceAccount, a namespaced read-only Role on applications.argoproj.io in argocd, the
gateway route/backend and a one-tool allow-list, plus a mcpServers/dependsOn entry and a
prompt note. No cluster, no AWS.

Run:  python -m pytest workshop/scripts/tests/test_aiops_argocd_status_chart.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "workshop", "aiops-agent", "chart")
TOOL = "argocd_unhealthy_applications"
BASE = ["--set-string", "accountId=111122223333", "--set", "clusterPrefix=peeks-x",
        "--set", "gitlabDomain=gitlab.example.com"]


def render(*extra):
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    out = subprocess.run(["helm", "template", "t", CHART, *BASE, *extra],
                         check=True, capture_output=True, text=True).stdout
    app = [d for d in yaml.safe_load_all(out) if d and d.get("kind") == "Application"][0]
    comps = {c["name"]: c for c in app["spec"]["components"]}
    agent = comps["aiops-agent"]
    return comps, [s["name"] for s in agent["properties"]["mcpServers"]], agent


def objs(comp, kind):
    return [o for o in comp["properties"]["objects"] if o["kind"] == kind]


def test_off_by_default_nothing_rendered():
    comps, servers, agent = render()
    assert "argocd-status-mcp" not in comps
    assert "argocd-status-mcp" not in servers
    assert "argocd-status-mcp" not in agent["dependsOn"]
    msg = agent["properties"]["systemMessage"]
    assert TOOL not in msg
    # prompt-only fallback (#1230) is kept
    assert "never answer that nothing is unhealthy from a sample" in msg


def test_global_image_tag_does_not_turn_it_on():
    comps, servers, _ = render("--set", "imageTag=v9")
    assert "argocd-status-mcp" not in comps and "argocd-status-mcp" not in servers


def test_on_adds_server_dependency_and_prompt_note():
    off_comps, off_servers, _ = render()
    comps, servers, agent = render("--set", "images.argocdStatusMcp.tag=v1")
    # the /ready set differs by exactly this server
    assert servers == off_servers + ["argocd-status-mcp"]
    assert "argocd-status-mcp" in agent["dependsOn"]
    assert set(comps) - set(off_comps) == {"argocd-status-mcp"}
    msg = agent["properties"]["systemMessage"]
    assert TOOL in msg and "never answer that nothing is unhealthy from a sample" in msg


def test_on_component_shape():
    comps, _, _ = render("--set", "images.argocdStatusMcp.tag=v1")
    c = comps["argocd-status-mcp"]
    assert c["type"] == "k8s-objects"
    assert c["properties"]["objects"][0]["kind"] == "Deployment"
    assert "traits" not in c  # no IAM / Pod Identity: in-cluster token only
    dep = objs(c, "Deployment")[0]
    pod = dep["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "argocd-status-mcp"
    ctr = pod["containers"][0]
    assert ctr["image"] == "public.ecr.aws/seb-demo/argocd-status-mcp:v1"
    assert ctr["securityContext"]["readOnlyRootFilesystem"] is True
    assert ctr["securityContext"]["allowPrivilegeEscalation"] is False
    assert [s["metadata"]["name"] for s in objs(c, "ServiceAccount")] == ["argocd-status-mcp"]


def test_rbac_is_namespaced_read_only_applications_only():
    comps, _, _ = render("--set", "images.argocdStatusMcp.tag=v1")
    c = comps["argocd-status-mcp"]
    assert not objs(c, "ClusterRole") and not objs(c, "ClusterRoleBinding")
    (role,) = objs(c, "Role")
    assert role["metadata"]["namespace"] == "argocd"
    assert role["rules"] == [{"apiGroups": ["argoproj.io"], "resources": ["applications"],
                              "verbs": ["get", "list"]}]
    (rb,) = objs(c, "RoleBinding")
    assert rb["metadata"]["namespace"] == "argocd"
    assert rb["roleRef"]["name"] == role["metadata"]["name"]
    assert rb["subjects"] == [{"kind": "ServiceAccount", "name": "argocd-status-mcp",
                               "namespace": "aiops-agent"}]


def test_gateway_route_and_one_tool_allow_list():
    comps, _, _ = render("--set", "images.argocdStatusMcp.tag=v1")
    c = comps["argocd-status-mcp"]
    (route,) = objs(c, "HTTPRoute")
    assert route["spec"]["rules"][0]["matches"][0]["path"]["value"] == "/mcp/argocd-status-mcp"
    (pol,) = objs(c, "AgentgatewayPolicy")
    authz = pol["spec"]["backend"]["mcp"]["authorization"]
    assert authz["action"] == "Require"
    assert authz["policy"]["matchExpressions"] == [f'mcp.tool.name in ["{TOOL}"]']


def test_registry_override():
    comps, _, _ = render("--set", "images.argocdStatusMcp.tag=v2",
                         "--set", "images.argocdStatusMcp.registry=123.dkr.ecr.us-east-1.amazonaws.com/x")
    ctr = objs(comps["argocd-status-mcp"], "Deployment")[0]["spec"]["template"]["spec"]["containers"][0]
    assert ctr["image"] == "123.dkr.ecr.us-east-1.amazonaws.com/x/argocd-status-mcp:v2"
