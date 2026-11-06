"""Amazon Managed Grafana reaper (§11): once the hub is gone the Crossplane provider
can't reap the AMG workspace, so delete directly. Match by name prefix."""

from ..context import name_is_ours


def owned_workspaces(ctx):
    """Our AMG workspaces (name <prefix>-...) that are not already being deleted."""
    return [ws for ws in ctx.grafana.list_workspaces().get("workspaces", [])
            if name_is_ours(ws.get("name") or "", ctx.prefix) and ws.get("status") != "DELETING"]


def reap(ctx, label=""):
    log, grafana = ctx.log, ctx.grafana
    try:
        deleted = 0
        for ws in owned_workspaces(ctx):
            try:
                grafana.delete_workspace(workspaceId=ws["id"])
                log(f"  {label}Deleted AMG workspace {ws['id']} ({ws.get('name')})")
                deleted += 1
            except Exception as e:
                log(f"  {label}AMG workspace {ws['id']}: {e}")
        if deleted == 0 and not label:
            log("No AMG workspaces to delete")
    except Exception as e:
        log(f"  {label}AMG workspaces: {e}")
