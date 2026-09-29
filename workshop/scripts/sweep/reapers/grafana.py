"""Amazon Managed Grafana reaper (§11): once the hub is gone the Crossplane provider
can't reap the AMG workspace, so delete directly. Match by name prefix."""


def reap(ctx):
    log, grafana, prefix = ctx.log, ctx.grafana, ctx.prefix
    try:
        deleted = 0
        for ws in grafana.list_workspaces().get("workspaces", []):
            if (ws.get("name") or "").startswith(prefix):
                try:
                    grafana.delete_workspace(workspaceId=ws["id"])
                    log(f"  Deleted AMG workspace {ws['id']} ({ws.get('name')})")
                    deleted += 1
                except Exception as e:
                    log(f"  AMG workspace {ws['id']}: {e}")
        if deleted == 0:
            log("No AMG workspaces to delete")
    except Exception as e:
        log(f"AMG workspaces: {e}")
