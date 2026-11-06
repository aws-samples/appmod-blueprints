"""AMP reaper (§5): managed scrapers create amp_collector ENIs that persist 5+ min
after deletion, blocking subnet deletion; also delete prefixed workspaces.
Scrapers are regional, so only ours (source cluster = our hub or a spoke) are deleted."""

from ..context import name_is_ours


def reap(ctx):
    log, amp, prefix = ctx.log, ctx.amp, ctx.prefix
    try:
        scrapers = [s for s in amp.list_scrapers().get("scrapers", []) if ctx.scraper_is_ours(s)]
        for s in scrapers:
            try:
                amp.delete_scraper(scraperId=s["scraperId"])
                log(f"  Deleted AMP scraper {s['scraperId']}")
            except Exception:
                pass
        delete_owned_workspaces(ctx)
        if not scrapers:
            log("No AMP scrapers to delete")
    except Exception as e:
        log(f"AMP: {e}")


def owned_workspaces(ctx):
    """Our AMP workspaces (alias <prefix>-...) that are not already being deleted."""
    return [ws for ws in ctx.amp.list_workspaces().get("workspaces", [])
            if name_is_ours(ws.get("alias", ""), ctx.prefix)
            and (ws.get("status") or {}).get("statusCode") != "DELETING"]


def delete_owned_workspaces(ctx, label=""):
    """Delete our AMP workspaces; returns how many deletes were accepted."""
    n = 0
    for ws in owned_workspaces(ctx):
        try:
            ctx.amp.delete_workspace(workspaceId=ws["workspaceId"])
            n += 1
            if label:
                ctx.log(f"  {label}Deleted AMP workspace {ws['workspaceId']} ({ws.get('alias')})")
        except Exception as e:
            if label:
                ctx.log(f"  {label}AMP workspace {ws['workspaceId']}: {e.__class__.__name__}")
    return n
