"""Pure filtering logic for argocd-status-mcp (no I/O, unit-tested).

An Argo CD Application is "not Synced and Healthy" when its sync status is not
`Synced` OR its health status is not `Healthy`. A missing status counts as
`Unknown`, so an app Argo CD has not reconciled yet is reported, never hidden.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

MESSAGE_MAX = 200

# Labels the platform stamps on addon Applications (appset-chart). Read, never required.
CLUSTER_LABEL = "clusterName"
ADDON_LABELS = ("addon", "addonName")


def _truncate(text: str, limit: int = MESSAGE_MAX) -> str:
    text = " ".join(str(text).split())  # one line: no newlines/indent in the row
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cluster(app: dict) -> str:
    dest = (app.get("spec") or {}).get("destination") or {}
    return dest.get("name") or dest.get("server") or ""


def _first_message(status: dict) -> str:
    """First condition message; else the health or operation message (often the only
    explanation for Degraded/Progressing or a failed sync)."""
    for cond in status.get("conditions") or []:
        if cond.get("message"):
            return _truncate(cond["message"])
    health = status.get("health") or {}
    if health.get("message"):
        return _truncate(health["message"])
    op = status.get("operationState") or {}
    # A Succeeded operation's message ("successfully synced") explains nothing about a
    # current OutOfSync; only a running/failed operation's message is useful.
    if op.get("message") and op.get("phase") != "Succeeded":
        return _truncate(op["message"])
    return ""


def _matches(app: dict, cluster: str | None, addon: str | None) -> bool:
    labels = (app.get("metadata") or {}).get("labels") or {}
    if cluster:
        dest = (app.get("spec") or {}).get("destination") or {}
        if cluster not in (labels.get(CLUSTER_LABEL), dest.get("name"), dest.get("server")):
            return False
    if addon:
        if addon not in tuple(labels.get(k) for k in ADDON_LABELS):
            return False
    return True


def app_row(app: dict) -> dict:
    status = app.get("status") or {}
    return {
        "name": (app.get("metadata") or {}).get("name", ""),
        "cluster": _cluster(app),
        "sync": (status.get("sync") or {}).get("status") or "Unknown",
        "health": (status.get("health") or {}).get("status") or "Unknown",
        "operation": (status.get("operationState") or {}).get("phase") or "",
        "message": _first_message(status),
    }


def is_unhealthy(row: dict) -> bool:
    return row["sync"] != "Synced" or row["health"] != "Healthy"


def summarize(
    apps: Iterable[dict],
    cluster: str | None = None,
    addon: str | None = None,
    max_rows: int = 200,
) -> dict:
    """Return totals plus one compact row per Application that is not Synced+Healthy.

    `total` counts the apps that passed the optional cluster/addon filters, so the
    caller can state its coverage ("N of M Applications are not Synced and Healthy").
    """
    total = 0
    rows = []
    for app in apps:
        if not _matches(app, cluster, addon):
            continue
        total += 1
        row = app_row(app)
        if is_unhealthy(row):
            rows.append(row)
    rows.sort(key=lambda r: (r["cluster"], r["name"]))
    by_state = Counter(f'{r["sync"]}/{r["health"]}' for r in rows)
    shown = rows[: max(0, max_rows)]
    return {
        "total": total,
        "unhealthy": len(rows),
        "by_state": dict(sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))),
        "filters": {k: v for k, v in (("cluster", cluster), ("addon", addon)) if v},
        "applications": shown,
        "truncated": len(rows) - len(shown),
    }
