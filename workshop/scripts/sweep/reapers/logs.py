"""CloudWatch Logs reapers: control-plane log groups (§9) and capability log
delivery objects (§12)."""

from ..resilience import run_delete


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
        _seen = set()
        _deleted = _gone = _access_denied = _failed = 0
        _errs = []
        for pfx in lg_prefixes:
            for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=pfx):
                for lg in page["logGroups"]:
                    name = lg["logGroupName"]
                    if name in _seen:
                        continue
                    _seen.add(name)
                    # run_delete: transient-retry + honest classification. The real
                    # AWS error code (AccessDenied vs DependencyViolation) is surfaced,
                    # instead of the old e.__class__.__name__ which was "ClientError"
                    # for every AWS error and hid the #932 mode.
                    kind, code, _msg = run_delete(lambda n=name: logs.delete_log_group(logGroupName=n))
                    if kind == "deleted":
                        _deleted += 1
                    elif kind == "gone":
                        _gone += 1
                    elif kind == "access_denied":
                        _access_denied += 1
                        _errs.append(f"{name}: AccessDenied")
                    else:
                        _failed += 1
                        _errs.append(f"{name}: {code}")
        # Report matched/deleted/failed explicitly — a prior version logged only
        # "No log groups to delete" when _deleted == 0, hiding an AccessDenied (#932).
        if not _seen:
            log("CloudWatch: no matching log groups found")
        else:
            log(
                f"CloudWatch: deleted {_deleted}/{len(_seen)} log group(s)"
                f"; {_access_denied} access-denied, {_failed} failed"
            )
            for m in _errs[:8]:
                log(f"  log-group delete failed — {m}")
    except Exception as e:
        log(f"CloudWatch: {e}")


def reap_deliveries(ctx):
    """§12. enable-capability-logs creates delivery-source/destination/delivery
    imperatively (<prefix>-*). Order matters: a source can't be deleted while a
    delivery references it."""
    log, logs, prefix = ctx.log, ctx.logs, ctx.prefix
    try:
        considered = reaped = access_denied = failed = 0

        def _reap(thunk, what):
            nonlocal considered, reaped, access_denied, failed
            considered += 1
            kind, code, msg = run_delete(thunk)
            if kind in ("deleted", "gone"):
                reaped += 1
            elif kind == "access_denied":
                access_denied += 1
                log(f"  {what}: ACCESS DENIED ({code})")
            else:
                failed += 1
                log(f"  {what}: failed ({kind}) {code}: {msg}")

        srcs = [
            s["name"]
            for s in logs.describe_delivery_sources().get("deliverySources", [])
            if s["name"].startswith(prefix)
        ]
        # deliveries first (a source can't be deleted while a delivery references it)
        for d in logs.describe_deliveries().get("deliveries", []):
            if d.get("deliverySourceName", "") in srcs:
                _reap(lambda i=d["id"]: logs.delete_delivery(id=i), f"delivery {d['id']}")
        for name in srcs:
            _reap(lambda n=name: logs.delete_delivery_source(name=n), f"delivery-source {name}")
        for dd in logs.describe_delivery_destinations().get("deliveryDestinations", []):
            if dd["name"].startswith(prefix):
                _reap(lambda n=dd["name"]: logs.delete_delivery_destination(name=n),
                      f"delivery-destination {dd['name']}")
        # Marker gated on "nothing considered", NOT on "0 reaped", so an all-denied run
        # is not mis-reported as "nothing to delete" (#932).
        if considered == 0:
            log("No CW Logs deliveries to delete")
        else:
            log(
                f"Reaped {reaped} CloudWatch Logs delivery object(s)"
                f"; {access_denied} access-denied, {failed} failed"
            )
    except Exception as e:
        log(f"CW Logs deliveries: {e}")
