"""EKS reapers: capabilities (§1), hub cluster (§6), orphaned spoke clusters (§6b)."""

from ..resilience import poll_until


def reap_capabilities(ctx):
    """§1. EKS Capabilities — must be deleted before delete-cluster, otherwise it
    fails with 'cluster has active capabilities'."""
    log, eks, hub = ctx.log, ctx.eks, ctx.hub
    try:
        caps = eks.list_capabilities(clusterName=hub).get("capabilities", [])
        if caps:
            log(f"Deleting {len(caps)} EKS capabilities ({', '.join(c['capabilityName'] for c in caps)})...")
            for cap in caps:
                try:
                    eks.delete_capability(clusterName=hub, capabilityName=cap["capabilityName"])
                except Exception:
                    pass
            if poll_until(
                lambda: not eks.list_capabilities(clusterName=hub).get("capabilities", []),
                attempts=20, delay=15,
            ):
                log("  Capabilities cleared")
        else:
            log("No EKS capabilities to delete")
    except Exception as e:
        log(f"Capabilities: {e}")


def reap_hub(ctx):
    """§6. Hub EKS cluster (direct AWS API delete, bypasses KRO). Waits up to 15 min
    so Auto Mode ENIs are released from the IDE VPC subnets. Sets ctx.hub_vpc_id."""
    log, eks = ctx.log, ctx.eks
    hub = ctx.hub
    try:
        _hub = eks.describe_cluster(name=hub)["cluster"]
        cluster_status = _hub["status"]
        ctx.hub_vpc_id = _hub.get("resourcesVpcConfig", {}).get("vpcId") or ctx.hub_vpc_id
        if cluster_status != "DELETING":
            eks.delete_cluster(name=hub)
            log("  Hub EKS cluster deletion submitted")
        else:
            log("  Hub EKS cluster already DELETING")
        # Wait up to 15 min (30 x 30 s). poll_until drives the retry cadence; the
        # closure captures the last observed status + emits the periodic progress log.
        _hub = {"status": "DELETING", "i": 0}

        def _hub_gone():
            try:
                _hub["status"] = eks.describe_cluster(name=hub)["cluster"]["status"]
            except eks.exceptions.ResourceNotFoundException:
                _hub["status"] = "NOT_FOUND"
                return True
            if _hub["i"] % 5 == 0:
                log(f"  [{_hub['i'] + 1}/30] Hub EKS: {_hub['status']}")
            _hub["i"] += 1
            return False

        poll_until(_hub_gone, attempts=30, delay=30)
        log(f"  Hub EKS: {'deleted' if _hub['status'] == 'NOT_FOUND' else _hub['status']}")
    except eks.exceptions.ResourceNotFoundException:
        log("  Hub EKS cluster already gone")
    except Exception as e:
        log(f"Hub EKS: {e}")


def reap_orphan_spokes(ctx):
    """§6b. Orphaned spoke EKS clusters left ACTIVE if `task destroy` was cut short.
    Delete capabilities, then the clusters, then wait for all to be gone."""
    log, eks, spokes = ctx.log, ctx.eks, ctx.spokes
    try:
        pending = []
        for spoke in spokes:
            try:
                eks.describe_cluster(name=spoke)  # existence probe (raises if gone)
            except eks.exceptions.ResourceNotFoundException:
                continue
            except Exception as e:
                log(f"  Spoke {spoke}: {e}")
                continue
            for cap in eks.list_capabilities(clusterName=spoke).get("capabilities", []):
                try:
                    eks.delete_capability(clusterName=spoke, capabilityName=cap["capabilityName"])
                except Exception:
                    pass
            pending.append(spoke)
        for spoke in pending:  # retry delete_cluster until capabilities finish deleting
            # ACK capabilities can take ~15-20 min to finish DELETING; delete_cluster
            # fails with ResourceInUseException until they clear. poll_until re-drives
            # the describe/delete predicate (up to ~25 min): it returns True as soon as
            # the delete is submitted or the cluster is already gone.
            _sp = {"i": 0}

            def _submit_spoke_delete(spoke=spoke, _sp=_sp):
                try:
                    if eks.describe_cluster(name=spoke)["cluster"]["status"] == "DELETING":
                        return True
                except eks.exceptions.ResourceNotFoundException:
                    return True
                except Exception:
                    pass
                try:
                    eks.delete_cluster(name=spoke)
                    log(f"  Spoke {spoke} deletion submitted")
                    return True
                except eks.exceptions.ResourceNotFoundException:
                    return True
                except Exception as e:
                    # Typically ResourceInUseException while capabilities are still DELETING.
                    if _sp["i"] % 8 == 0:
                        log(f"  Spoke {spoke}: waiting for capabilities to clear before delete ({e.__class__.__name__})")
                    _sp["i"] += 1
                    return False

            submitted = poll_until(_submit_spoke_delete, attempts=100, delay=15)  # ~25 min
            if not submitted:
                log(f"  Spoke {spoke}: delete still blocked after ~25 min — leaving for the next sweep")
        for spoke in pending:  # wait up to ~15 min per spoke for full deletion
            def _spoke_gone(spoke=spoke):
                try:
                    eks.describe_cluster(name=spoke)
                    return False
                except eks.exceptions.ResourceNotFoundException:
                    log(f"  Spoke {spoke}: deleted")
                    return True
                except Exception:
                    return True  # give up waiting on any other error (matches prior break)

            poll_until(_spoke_gone, attempts=30, delay=30)
        if not pending:
            log("No orphaned spoke clusters to delete")
    except Exception as e:
        log(f"Orphaned spoke clusters: {e}")
