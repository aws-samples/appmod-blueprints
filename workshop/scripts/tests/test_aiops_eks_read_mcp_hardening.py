"""Hermetic tests for the eks-read-mcp hardening in the aiops-agent chart.

`helm template` renders workshop/aiops-agent/chart; the KubeVela Application is read as
YAML. Checks: explicit --no-allow-write, own ServiceAccount + Pod Identity trait (the
agent role keeps only the AgentCore memory policy), image pinned by digest, a gateway
tool allow-list that leaves out the write-only tools, and AccessEntries for the MCP role.
No cluster, no AWS.

Run:  python -m pytest workshop/scripts/tests/test_aiops_eks_read_mcp_hardening.py -q
"""
import hashlib
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "workshop", "aiops-agent", "chart")
WRITE_ONLY_TOOLS = ["apply_yaml", "generate_app_manifest", "manage_eks_stacks", "add_inline_policy"]


@pytest.fixture(scope="module")
def components():
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    out = subprocess.run(
        ["helm", "template", "t", CHART, "--set-string", "accountId=111122223333",
         "--set", "clusterPrefix=peeks-x"],
        check=True, capture_output=True, text=True).stdout
    app = [d for d in yaml.safe_load_all(out) if d and d.get("kind") == "Application"][0]
    return {c["name"]: c for c in app["spec"]["components"]}


def _objects(comp, kind):
    return [o for o in comp["properties"]["objects"] if o["kind"] == kind]


def test_deployment_is_first_object_so_the_trait_patches_it(components):
    # k8s-objects: objects[0] is the component `output`, the only object a trait patches.
    assert components["eks-read-mcp"]["properties"]["objects"][0]["kind"] == "Deployment"


def test_explicit_no_allow_write(components):
    dep = _objects(components["eks-read-mcp"], "Deployment")[0]
    c = dep["spec"]["template"]["spec"]["containers"][0]
    # `command`, not `args`: the image sets the supergateway line as ENTRYPOINT.
    assert "args" not in c
    stdio = c["command"][c["command"].index("--stdio") + 1]
    assert "--no-allow-write" in stdio.split()
    assert "--allow-write" not in stdio.split()


def test_own_service_account_and_pod_identity(components):
    mcp = components["eks-read-mcp"]
    dep = _objects(mcp, "Deployment")[0]
    assert dep["spec"]["template"]["spec"]["serviceAccountName"] == "eks-read-mcp"
    assert [o["metadata"]["name"] for o in _objects(mcp, "ServiceAccount")] == ["eks-read-mcp"]
    traits = {t["type"]: t for t in mcp.get("traits", [])}
    assert traits["aws-service-identity"]["properties"]["accessFor"] == ["eks-read-access"]
    # The trait injects the region and creds env; a second copy here would conflict.
    names = [e["name"] for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", [])]
    assert "AWS_REGION" not in names and "AWS_DEFAULT_REGION" not in names


def test_agent_role_keeps_only_memory(components):
    traits = {t["type"]: t for t in components["aiops-agent"]["traits"]}
    assert traits["aws-service-identity"]["properties"]["accessFor"] == ["aiops-agent-memory"]


def test_image_pinned_by_digest(components):
    dep = _objects(components["eks-read-mcp"], "Deployment")[0]
    image = dep["spec"]["template"]["spec"]["containers"][0]["image"]
    assert re.search(r"/eks-mcp:[^@]+@sha256:[0-9a-f]{64}$", image), image


def test_tool_allow_list_excludes_write_only_tools(components):
    pol = _objects(components["eks-read-mcp"], "AgentgatewayPolicy")
    assert len(pol) == 1
    spec = pol[0]["spec"]
    assert spec["targetRefs"] == [{"group": "agentgateway.dev", "kind": "AgentgatewayBackend",
                                   "name": "eks-read-mcp-backend"}]
    authz = spec["backend"]["mcp"]["authorization"]
    assert authz["action"] == "Require"
    [expr] = authz["policy"]["matchExpressions"]
    allowed = re.fullmatch(r"mcp\.tool\.name in \[(.*)\]", expr).group(1)
    allowed = [t.strip().strip('"') for t in allowed.split(",")]
    assert "list_k8s_resources" in allowed and "get_pod_logs" in allowed
    for tool in WRITE_ONLY_TOOLS:
        assert tool not in allowed


def _platform_role_name(region, cluster, namespace, sa):
    # Same rule as the aws-service-identity trait (platform/oam/definitions/traits/).
    digest = hashlib.sha256(f"{region}/{cluster}/{namespace}/{sa}".encode()).hexdigest()[:8]
    return f"{f'{cluster}-{sa}'[:50]}-{digest}-role"


def test_access_entries_use_the_mcp_role(components):
    role = _platform_role_name("us-west-2", "peeks-x-hub", "aiops-agent", "eks-read-mcp")
    assert role != _platform_role_name("us-west-2", "peeks-x-hub", "aiops-agent", "aiops-agent")
    entries = _objects(components["agent-access"], "AccessEntry")
    # Hub only: spoke entries come from the spoke-access ApplicationSet (#1208).
    assert [e["metadata"]["name"] for e in entries] == [f"{role}-hub"]
    for e in entries:
        assert e["spec"]["principalARN"] == f"arn:aws:iam::111122223333:role/{role}"
        assert e["spec"]["kubernetesGroups"] == ["aiops-agent-cluster-read"]


def test_spoke_access_appset_names_the_mcp_role():
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    out = subprocess.run(
        ["helm", "template", "t", CHART, "--set-string", "accountId=111122223333",
         "--set", "clusterPrefix=peeks-x"],
        check=True, capture_output=True, text=True).stdout
    [appset] = [d for d in yaml.safe_load_all(out) if d and d.get("kind") == "ApplicationSet"]
    vals = appset["spec"]["template"]["spec"]["source"]["helm"]["valuesObject"]
    assert vals["roleName"] == _platform_role_name("us-west-2", "peeks-x-hub", "aiops-agent",
                                                   "eks-read-mcp")
