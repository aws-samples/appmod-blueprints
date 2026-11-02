"""Hermetic tests for argocd-status-mcp server.py: pagination over the Kubernetes list
API (limit/continue) and the MCP tool end to end through an in-memory FastMCP client.
The Kubernetes API is stubbed; no cluster, no network. Skips without fastmcp.

Run:  python -m pytest workshop/scripts/tests/test_aiops_argocd_status_server.py -q
"""
import asyncio
import json
import os
import sys

import pytest

pytest.importorskip("fastmcp")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "workshop", "aiops-agent", "src", "argocd-status-mcp"))

import server  # noqa: E402


def _app(name, sync="Synced", health="Healthy"):
    return {"metadata": {"name": name, "labels": {"clusterName": "hub"}},
            "spec": {"destination": {"name": "hub"}},
            "status": {"sync": {"status": sync}, "health": {"status": health}}}


@pytest.fixture
def fake_api(monkeypatch):
    pages = {
        "": {"items": [_app("a"), _app("b", sync="Unknown")], "metadata": {"continue": "t1"}},
        "t1": {"items": [_app("c", health="Degraded")], "metadata": {"continue": "t2"}},
        "t2": {"items": [_app("d")], "metadata": {}},
    }
    calls = []

    def fake_get(url):
        calls.append(url)
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)
        assert q["limit"] == [str(server.PAGE)]
        return pages[q.get("continue", [""])[0]]

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setattr(server, "_get", fake_get)
    return calls


def test_lists_every_page_of_the_argocd_namespace(fake_api):
    names = [a["metadata"]["name"] for a in server.list_applications()]
    assert names == ["a", "b", "c", "d"]
    assert len(fake_api) == 3
    assert all("/apis/argoproj.io/v1alpha1/namespaces/argocd/applications?" in u for u in fake_api)


def test_tool_end_to_end_through_mcp(fake_api):
    from fastmcp import Client

    async def run():
        async with Client(server.mcp) as c:
            tools = {t.name for t in await c.list_tools()}
            res = await c.call_tool("argocd_unhealthy_applications", {})
            return tools, res

    tools, res = asyncio.run(run())
    assert tools == {"argocd_unhealthy_applications"}
    data = res.structured_content if getattr(res, "structured_content", None) else json.loads(res.content[0].text)
    assert data["total"] == 4 and data["unhealthy"] == 2
    assert [r["name"] for r in data["applications"]] == ["b", "c"]


def test_api_error_is_reported_never_a_partial_answer(monkeypatch):
    import urllib.error

    def fail(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setattr(server, "_get", fail)
    with pytest.raises(RuntimeError, match="403.*No partial result"):
        server.argocd_unhealthy_applications.fn() if hasattr(
            server.argocd_unhealthy_applications, "fn") else server.argocd_unhealthy_applications()
