#!/usr/bin/env python3
"""
argocd-status-mcp — a tiny READ-ONLY FastMCP (StreamableHTTP) server that answers
"which Argo CD Applications are not Synced and Healthy?" completely and cheaply.

Why it exists: the upstream eks-mcp-server's list_k8s_resources returns no status and
status cannot be field-selected, so a full sweep means reading every Application
(~33 KB each, 180+ on a loaded hub). This server lists them in-cluster, page by page,
and returns only totals plus one compact row per app that is not Synced+Healthy.

Access: the pod's own ServiceAccount token (in-cluster), bound to a Role that only
allows get/list on applications.argoproj.io in the Argo CD namespace. No IAM, no
secrets, no writes. The namespace is fixed by ARGOCD_NAMESPACE (default "argocd"),
the namespace the RBAC grants; it is not a tool argument.

Tool:
  - argocd_unhealthy_applications(cluster=None, addon=None)

Transport: StreamableHTTP on :8000 /mcp, stateless + JSON responses, like skills-mcp.
"""
import json
import os
import ssl
import urllib.parse
import urllib.request

from fastmcp import FastMCP

from status import summarize

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
NAMESPACE = os.getenv("ARGOCD_NAMESPACE", "argocd")
PAGE = int(os.getenv("PAGE_SIZE", "50"))
# 50 rows x ~300 chars stays near 4k tokens even on a badly broken hub; counts stay exact.
MAX_ROWS = int(os.getenv("MAX_ROWS", "50"))
TIMEOUT = float(os.getenv("K8S_TIMEOUT_SECONDS", "20"))

mcp = FastMCP("argocd-status")


def _api_base() -> str:
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
    if ":" in host:  # IPv6
        host = f"[{host}]"
    return f"https://{host}:{port}"


def _get(url: str) -> dict:
    with open(os.path.join(SA_DIR, "token"), encoding="utf-8") as fh:
        token = fh.read().strip()  # re-read each call: projected tokens rotate
    ctx = ssl.create_default_context(cafile=os.path.join(SA_DIR, "ca.crt"))
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT) as resp:
        return json.load(resp)


def list_applications(namespace: str = NAMESPACE):
    """Yield every Application in *namespace*, paginated (limit/continue)."""
    path = f"/apis/argoproj.io/v1alpha1/namespaces/{urllib.parse.quote(namespace)}/applications"
    cont = ""
    while True:
        q = {"limit": str(PAGE)}
        if cont:
            q["continue"] = cont
        page = _get(f"{_api_base()}{path}?{urllib.parse.urlencode(q)}")
        yield from page.get("items") or []
        cont = (page.get("metadata") or {}).get("continue") or ""
        if not cont:
            return


@mcp.tool()
def argocd_unhealthy_applications(cluster: str | None = None, addon: str | None = None) -> dict:
    """List the Argo CD Applications on the hub that are NOT both Synced and Healthy.

    Reads EVERY Application (no sampling) and returns:
      total        Applications read (after the optional filters) — your coverage;
      unhealthy    how many are not Synced+Healthy;
      by_state     counts per "<sync>/<health>";
      applications one row per not-green app: name, cluster and namespace
                   (destination), sync, health, operation (operationState.phase),
                   message (first condition, else health/operation message, max 200
                   chars); at most 50 rows by default, sorted by cluster then name;
      truncated    rows left out past the row cap (counts stay exact).
    A missing status counts as Unknown. Optional filters: `cluster` (destination
    name/server or the clusterName label) and `addon` (the addon/addonName label).
    Answer with "<unhealthy> of <total> Applications are not Synced and Healthy".
    """
    try:
        return summarize(list_applications(), cluster=cluster or None,
                         addon=addon or None, max_rows=MAX_ROWS)
    except Exception as exc:  # report a clear cause; never a partial (sampled) answer
        raise RuntimeError(
            f"could not list Applications in namespace {NAMESPACE!r}: {type(exc).__name__}: {exc}. "
            "No partial result is returned; do not conclude anything about Application health "
            "from this call.") from exc


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    """Readiness/liveness: the process serves HTTP. It does not call the API server,
    so a slow API server never flaps the pod (the tool reports API errors itself)."""
    from starlette.responses import PlainTextResponse
    return PlainTextResponse("ok")


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        stateless_http=True,
        json_response=True,
    )
