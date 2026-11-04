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


# --- ISSUE-A scenario: the fleet-wide question on a loaded hub ------------------------
# Live hub (read-only sample): 183 Applications, 6,109,400 bytes as JSON (~33 KB each).
# Without this tool the chat read Applications one by one (~8-10k tokens per read) and
# stopped at 12 of 183. The tool must answer in ONE call, find the one unhealthy app,
# and return a result that fits a small token budget.

N_APPS = 183
CHARS_PER_TOKEN = 4  # conservative for JSON with short keys


def _fat_app(i, sync="Synced", health="Healthy", message=None):
    """An Application about the size of a live one (~33 KB): status.resources carries
    the managed-resource list, which is most of the bytes of a real Application."""
    name = f"addon-{i:03d}-peeks-spoke-{('dev', 'staging', 'prod')[i % 3]}"
    st = {"sync": {"status": sync, "revision": "f" * 40},
          "health": {"status": health},
          "operationState": {"phase": "Succeeded", "message": "successfully synced (all tasks run)"},
          "resources": [{"group": "apps", "kind": "Deployment", "namespace": "ns",
                         "name": f"r{j}-" + "x" * 200, "status": "Synced",
                         "health": {"status": "Healthy"}, "version": "v1"} for j in range(110)]}
    if message:
        st["conditions"] = [{"type": "ComparisonError", "message": message}]
    return {"metadata": {"name": name, "namespace": "argocd",
                         "labels": {"clusterName": name.split("-", 2)[2], "addonName": f"addon-{i:03d}"},
                         "annotations": {"kubectl.kubernetes.io/last-applied-configuration": "y" * 2000}},
            "spec": {"destination": {"name": name.split("-", 2)[2], "namespace": f"ns-{i:03d}"},
                     "source": {"repoURL": "https://example.com/r.git", "path": "p", "targetRevision": "main"}},
            "status": st}


def _paged_api(monkeypatch, apps):
    pages = [apps[i:i + server.PAGE] for i in range(0, len(apps), server.PAGE)]
    calls = []

    def fake_get(url):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)
        idx = int(q.get("continue", ["0"])[0])
        calls.append(idx)
        nxt = str(idx + 1) if idx + 1 < len(pages) else ""
        return {"items": pages[idx], "metadata": {"continue": nxt} if nxt else {}}

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setattr(server, "_get", fake_get)
    return calls


def _call_tool(args=None):
    from fastmcp import Client

    async def run():
        async with Client(server.mcp) as c:
            return await c.call_tool("argocd_unhealthy_applications", args or {})

    res = asyncio.run(run())
    text = res.content[0].text  # what the model reads (strands maps `content` to the model)
    return json.loads(text), text


def test_issue_a_183_apps_one_unhealthy_found_in_one_call_within_budget(monkeypatch):
    apps = [_fat_app(i) for i in range(N_APPS)]
    apps[117] = _fat_app(117, sync="Unknown", message=(
        "Failed to load target state: failed to generate manifest for source 4 of 4: "
        "rpc error: code = InvalidArgument desc = failed to execute helm template command"))
    raw = len(json.dumps({"items": apps}))
    assert raw > 5_000_000  # same order as the live 6.1 MB read
    calls = _paged_api(monkeypatch, apps)

    data, text = _call_tool()

    assert calls == [0, 1, 2, 3]  # every page read: 183 apps / limit 50
    assert data["total"] == N_APPS and data["unhealthy"] == 1 and data["truncated"] == 0
    (row,) = data["applications"]
    assert row["name"] == apps[117]["metadata"]["name"]
    assert row["sync"] == "Unknown" and row["health"] == "Healthy"
    assert row["namespace"] == "ns-117" and row["cluster"] == "peeks-spoke-dev"
    assert row["message"].startswith("Failed to load target state")
    assert set(row) == {"name", "cluster", "namespace", "sync", "health", "operation", "message"}
    # Token budget: one call, a few hundred tokens, versus ~8-10k tokens per Application read.
    assert len(text) / CHARS_PER_TOKEN < 300, len(text)
    assert len(text) * 10_000 < raw  # < 0.01% of the raw read


def test_issue_a_all_green_183_apps_says_so_with_full_coverage(monkeypatch):
    _paged_api(monkeypatch, [_fat_app(i) for i in range(N_APPS)])
    data, text = _call_tool()
    assert data["total"] == N_APPS and data["unhealthy"] == 0 and data["applications"] == []
    assert len(text) / CHARS_PER_TOKEN < 100


def test_worst_case_every_app_broken_stays_bounded(monkeypatch):
    long_msg = "ComparisonError: " + "z" * 1000
    _paged_api(monkeypatch, [_fat_app(i, sync="OutOfSync", health="Degraded", message=long_msg)
                             for i in range(N_APPS)])
    data, text = _call_tool()
    assert data["total"] == N_APPS and data["unhealthy"] == N_APPS
    assert len(data["applications"]) == server.MAX_ROWS == 50
    assert data["truncated"] == N_APPS - 50
    assert data["by_state"] == {"OutOfSync/Degraded": N_APPS}  # counts stay exact
    assert len(text) / CHARS_PER_TOKEN < 5_000, len(text)
