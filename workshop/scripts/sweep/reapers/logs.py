"""CloudWatch Logs reapers: control-plane log groups (§9) and capability log
delivery objects (§12)."""


def reap_log_groups(ctx):
    """§9. EKS control-plane / container-insights log groups survive cluster deletion."""
    log, logs, prefix, hub, spokes = ctx.log, ctx.logs, ctx.prefix, ctx.hub, ctx.spokes
    try:
        clusters_for_logs = [hub] + spokes
        # Broad /aws/eks/<prefix> + /aws/containerinsights/<prefix> prefixes catch
        # EVERY owned cluster's log groups, including arbitrarily-named #914 spokes.
        lg_prefixes = sorted(set(
            [f"/aws/eks/{prefix}", f"/aws/containerinsights/{prefix}"]
            + [f"/aws/eks/{c}" for c in clusters_for_logs]
            + [f"/aws/containerinsights/{c}" for c in clusters_for_logs]
            + [f"/aws/lambda/{prefix}-"]
        ))
        _seen, _lg_deleted, _lg_errs = set(), 0, []
        for pfx in lg_prefixes:
            for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=pfx):
                for lg in page["logGroups"]:
                    name = lg["logGroupName"]
                    if name in _seen:
                        continue
                    _seen.add(name)
                    try:
                        logs.delete_log_group(logGroupName=name)
                        _lg_deleted += 1
                    except Exception as e:
                        _lg_errs.append(f"{name}: {e.__class__.__name__}")
        # Report matched/deleted/failed explicitly — a prior version logged only
        # "No log groups to delete" when _lg_deleted == 0, hiding an AccessDenied (#932).
        if not _seen:
            log("CloudWatch: no matching log groups found")
        else:
            log(f"CloudWatch: deleted {_lg_deleted}/{len(_seen)} log group(s)")
            for m in _lg_errs[:8]:
                log(f"  log-group delete failed — {m}")
    except Exception as e:
        log(f"CloudWatch: {e}")


def reap_deliveries(ctx):
    """§12. enable-capability-logs creates delivery-source/destination/delivery
    imperatively (<prefix>-*). Order matters: a source can't be deleted while a
    delivery references it."""
    log, logs, prefix = ctx.log, ctx.logs, ctx.prefix
    try:
        reaped = 0
        srcs = [
            s["name"]
            for s in logs.describe_delivery_sources().get("deliverySources", [])
            if s["name"].startswith(prefix)
        ]
        for d in logs.describe_deliveries().get("deliveries", []):
            if d.get("deliverySourceName", "") in srcs:
                try:
                    logs.delete_delivery(id=d["id"])
                    reaped += 1
                except Exception:
                    pass
        for name in srcs:
            try:
                logs.delete_delivery_source(name=name)
                reaped += 1
            except Exception as e:
                log(f"  delivery-source {name}: {e}")
        for dd in logs.describe_delivery_destinations().get("deliveryDestinations", []):
            if dd["name"].startswith(prefix):
                try:
                    logs.delete_delivery_destination(name=dd["name"])
                    reaped += 1
                except Exception:
                    pass
        log(f"Reaped {reaped} CloudWatch Logs delivery object(s)" if reaped else "No CW Logs deliveries to delete")
    except Exception as e:
        log(f"CW Logs deliveries: {e}")
