"""AMP reaper (§5): managed scrapers create amp_collector ENIs that persist 5+ min
after deletion, blocking subnet deletion; also delete prefixed workspaces.
Scrapers are regional, so only ours (source cluster = our hub or a spoke) are deleted."""


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
        for ws in amp.list_workspaces()["workspaces"]:
            if ws.get("alias", "").startswith(prefix):
                try:
                    amp.delete_workspace(workspaceId=ws["workspaceId"])
                except Exception:
                    pass
        if not scrapers:
            log("No AMP scrapers to delete")
    except Exception as e:
        log(f"AMP: {e}")
