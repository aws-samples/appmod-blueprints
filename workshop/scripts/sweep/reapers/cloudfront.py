"""CloudFront reaper (§2): VPC Origin + Distribution.

The VPC Origin keeps a cloudfront_managed ENI in the IDE VPC subnets. The
distribution must be disabled then deleted before the VPC Origin can be removed.
(The re-sweep variant for Crossplane-recreated distributions lives in resweep.py §16d.)
"""

import time

from ..resilience import poll_until


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
            resp = cf.get_distribution_config(Id=dist_id)
            etag, cfg = resp["ETag"], resp["DistributionConfig"]
            if cfg.get("Enabled", True):
                cfg["Enabled"] = False
                cf.update_distribution(Id=dist_id, DistributionConfig=cfg, IfMatch=etag)
                log(f"  Disabling CF distribution {dist_id} (waiting for Deployed)...")
                poll_until(
                    lambda dist_id=dist_id: cf.get_distribution(Id=dist_id)["Distribution"]["Status"] == "Deployed",
                    attempts=20, delay=15,
                )
            etag2 = cf.get_distribution(Id=dist_id)["ETag"]
            cf.delete_distribution(Id=dist_id, IfMatch=etag2)
            log(f"  Deleted CF distribution {dist_id}")

        # Small delay so ENIs detach before VPC Origin deletion
        if dist_ids:
            time.sleep(5)

        for vo_id in vo_ids:
            etag = cf.get_vpc_origin(Id=vo_id)["ETag"]
            cf.delete_vpc_origin(Id=vo_id, IfMatch=etag)
            log(f"  Deleted CF VPC origin {vo_id}")

        if not dist_ids and not vo_ids:
            log("No CloudFront distributions/VPC origins to delete")
    except Exception as e:
        log(f"CloudFront: {e}")
