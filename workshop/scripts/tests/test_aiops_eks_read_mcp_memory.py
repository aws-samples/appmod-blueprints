"""eks-read-mcp is sized for parallel tool calls, and the agent prompt describes its tools as they are.

Why (ISSUE-A, int1103 run): supergateway 4.x serves every MCP 2026-07-28 request with a fresh
`awslabs.eks-mcp-server` stdio child (~100-125 MiB, even with --stateful), and the strands agent runs
all tool calls of one model turn at once. 12 parallel Application reads (~1.25 GiB of children)
OOMKilled the 1Gi container. The upstream 0.2.1 tools have no filter / JMESPath argument: an extra
argument is dropped by the MCP argument model and the full object comes back.

- the eks-read-mcp container limit is at least 2Gi (request unchanged at 512Mi, so scheduling
  does not change);
- the system prompt says the eks-read tools take no filter/JMESPath argument and caps eks-read
  calls at 4 in parallel; it never suggests a JMESPath/jq filter.

Run:  python -m pytest workshop/scripts/tests/test_aiops_eks_read_mcp_memory.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "workshop", "aiops-agent", "chart")
HELM = shutil.which("helm")
pytestmark = pytest.mark.skipif(HELM is None, reason="helm not on PATH")

UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30}


def mem_bytes(q):
    for suffix, mult in UNITS.items():
        if q.endswith(suffix):
            return int(q[: -len(suffix)]) * mult
    return int(q)


@pytest.fixture(scope="module")
def vela_app():
    out = subprocess.run([HELM, "template", "t", CHART], capture_output=True, text=True, check=True).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    apps = [d for d in docs if d.get("kind") == "Application" and d.get("apiVersion", "").startswith("core.oam.dev")]
    assert len(apps) == 1
    return apps[0]


def component(app, name):
    return next(c for c in app["spec"]["components"] if c["name"] == name)


def test_eks_read_mcp_memory_sized_for_parallel_calls(vela_app):
    deploy = component(vela_app, "eks-read-mcp")["properties"]["objects"][0]
    assert deploy["kind"] == "Deployment"
    res = deploy["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert mem_bytes(res["limits"]["memory"]) >= 2 * 2**30
    assert mem_bytes(res["requests"]["memory"]) == 512 * 2**20


def test_prompt_describes_eks_read_tools_as_they_are(vela_app):
    prompt = component(vela_app, "aiops-agent")["properties"]["systemMessage"]
    note = prompt[prompt.index("`eks-read` MCP"):]
    note = note[: note.index("\n- `")] if "\n- `" in note else note
    assert "NO filter, query, JMESPath" in note
    assert "silently ignored" in note
    assert "at most 4 eks-read calls in parallel" in note
    # Nothing in the prompt may suggest a JMESPath/jq projection on eks-read output.
    low = prompt.lower()
    for bad in ("jmespath=", "jmespath:", "--query", "jq '", "use jmespath", "a jmespath filter"):
        assert bad not in low, bad
