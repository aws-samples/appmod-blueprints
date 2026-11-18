"""CloudFront reaper (§2): VPC Origin + Distribution.

The VPC Origin keeps a cloudfront_managed ENI in the IDE VPC subnets. The
distribution must be disabled then deleted before the VPC Origin can be removed.
(The re-sweep variant for Crossplane-recreated distributions lives in resweep.py §16d.)
"""

import time

from ..resilience import poll_until


# A CloudFront disable takes ~5-15 min to reach Deployed; the delete is refused
# (DistributionNotDisabled) until then. 80 x 15 s = 20 min.
DEPLOYED_ATTEMPTS = 80
DEPLOYED_DELAY = 15
# After a DistributionNotDisabled refusal, wait only briefly (2 min) before the retry:
# the 20 min budget above is spent once per distribution, worst case ~24 min.
RETRY_ATTEMPTS = 8
DELETE_TRIES = 3


def _error_code(exc):
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def disable_and_delete(cf, dist_id, log, tag=""):
    """Disable `dist_id` if needed, wait until it is Deployed, then delete it.

    The wait runs whether the distribution was just disabled or already was
    (Enabled=False can still be InProgress). Never raises: returns True when the
    distribution is gone, so the caller always goes on to the VPC-origin delete.
    """
    def deployed():
        try:
            return cf.get_distribution(Id=dist_id)["Distribution"]["Status"] == "Deployed"
        except Exception as e:  # throttling etc.: keep polling, do not end the wait early
            if _error_code(e) == "NoSuchDistribution":
                raise
            return False

    try:
        resp = cf.get_distribution_config(Id=dist_id)
        etag, cfg = resp["ETag"], resp["DistributionConfig"]
        if cfg.get("Enabled", True):
            cfg["Enabled"] = False
            cf.update_distribution(Id=dist_id, DistributionConfig=cfg, IfMatch=etag)
            log(f"  {tag}Disabling CF distribution {dist_id}...")
        log(f"  {tag}Waiting for CF distribution {dist_id} to be Deployed...")
        if not poll_until(deployed, attempts=DEPLOYED_ATTEMPTS, delay=DEPLOYED_DELAY):
            log(f"  {tag}CF distribution {dist_id} not Deployed after "
                f"{DEPLOYED_ATTEMPTS * DEPLOYED_DELAY}s; trying the delete anyway")
        for attempt in range(1, DELETE_TRIES + 1):
            try:
                etag2 = cf.get_distribution(Id=dist_id)["ETag"]
                cf.delete_distribution(Id=dist_id, IfMatch=etag2)
                log(f"  {tag}Deleted CF distribution {dist_id}")
                return True
            except Exception as e:
                code = _error_code(e)
                if code == "NoSuchDistribution":
                    return True
                if code == "DistributionNotDisabled" and attempt < DELETE_TRIES:
                    log(f"  {tag}CF distribution {dist_id} not disabled yet; waiting and retrying")
                    poll_until(deployed, attempts=RETRY_ATTEMPTS, delay=DEPLOYED_DELAY)
                    continue
                raise
    except Exception as e:
        log(f"  {tag}CF distribution {dist_id} not deleted: {e}")
    return False


def reap(ctx):
    log, cf, hub = ctx.log, ctx.cf, ctx.hub
    try:
        vos = cf.list_vpc_origins().get("VpcOriginList", {}).get("Items", [])
        vo_ids = {vo["Id"] for vo in vos if vo.get("Name", "").startswith(hub + "-")}

        dist_ids = set()
        dists = cf.list_distributions().get("DistributionList", {}).get("Items", [])
        for d in dists:
            if d.get("Comment", "").startswith(hub):
                dist_ids.add(d["Id"])
                continue
            for o in d.get("Origins", {}).get("Items", []):
                if o.get("VpcOriginConfig", {}).get("VpcOriginId", "") in vo_ids:
                    dist_ids.add(d["Id"])

        for dist_id in dist_ids:
            disable_and_delete(cf, dist_id, log)

        # Small delay so ENIs detach before VPC Origin deletion
        if dist_ids:
            time.sleep(5)

        for vo_id in vo_ids:
            try:
                etag = cf.get_vpc_origin(Id=vo_id)["ETag"]
                cf.delete_vpc_origin(Id=vo_id, IfMatch=etag)
                log(f"  Deleted CF VPC origin {vo_id}")
            except Exception as e:
                log(f"  CF VPC origin {vo_id} not deleted: {e}")

        if not dist_ids and not vo_ids:
            log("No CloudFront distributions/VPC origins to delete")
    except Exception as e:
        log(f"CloudFront: {e}")
