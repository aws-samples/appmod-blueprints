"""Final authoritative re-sweep (§16): re-delete CloudFront/ALB/RDS/AMP that the
still-alive hub controllers may have RE-CREATED before §6/§6b killed them, re-clear
the IDE VPC SGs, then wait (ENI gate) for service-managed ENIs to detach so CFN can
delete the subnets. Cheap when nothing was recreated (the common case)."""

import time

from ..resilience import poll_until
from . import elb


def run(ctx):
    log, ec2, cf, amp, rds, elbv2 = ctx.log, ctx.ec2, ctx.cf, ctx.amp, ctx.rds, ctx.elbv2
    hub = ctx.hub
    _is_our_ide_vpc, _delete_vpc_sgs = ctx.is_our_ide_vpc, ctx.delete_vpc_sgs
    try:
        def _find_ide_vpc():
            """The IDE VPC of THIS workshop. Requires the CFN stack name to reference
            this deployment, and refuses to guess when ambiguous (SAFETY: never pick a
            VPC just because it carries an aws:cloudformation:* tag)."""
            if ctx.hub_vpc_id:
                return ctx.hub_vpc_id
            matches = [
                v["VpcId"]
                for v in ec2.describe_vpcs().get("Vpcs", [])
                if _is_our_ide_vpc({t["Key"]: t["Value"] for t in v.get("Tags", [])})
            ]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                log("  [re-sweep] No IDE VPC identified for this deployment — skipping IDE VPC steps")
            else:
                log(f"  [re-sweep] {len(matches)} candidate IDE VPCs ({', '.join(matches)}) — "
                    "ambiguous, refusing to guess; skipping IDE VPC steps")
            return None

        ide_vpc = _find_ide_vpc()

        # 16a. AMP scrapers (recreated by the AMP capability / addon)
        try:
            for s in amp.list_scrapers().get("scrapers", []):
                try:
                    amp.delete_scraper(scraperId=s["scraperId"])
                    log(f"  [re-sweep] Deleted recreated AMP scraper {s['scraperId']}")
                except Exception:
                    pass
        except Exception as e:
            log(f"  [re-sweep] AMP: {e}")

        # 16b. ALBs (recreated by the AWS Load Balancer Controller). Reuses the shared
        #      elb.lb_owned predicate (prefix name OR LB-controller/#914 ownership tag).
        try:
            for lb in elbv2.describe_load_balancers()["LoadBalancers"]:
                if elb.lb_owned(ctx, lb["LoadBalancerArn"], lb["LoadBalancerName"]):
                    elbv2.delete_load_balancer(LoadBalancerArn=lb["LoadBalancerArn"])
                    log(f"  [re-sweep] Deleted recreated ALB {lb['LoadBalancerName']}")
        except Exception as e:
            log(f"  [re-sweep] ALB: {e}")

        # 16c. RDS (recreated by ACK)
        try:
            for db in rds.describe_db_instances()["DBInstances"]:
                if db["DBInstanceIdentifier"].startswith("devlake") \
                   and db["DBInstanceStatus"] not in ("deleting",):
                    rds.delete_db_instance(
                        DBInstanceIdentifier=db["DBInstanceIdentifier"],
                        SkipFinalSnapshot=True,
                        DeleteAutomatedBackups=True,
                    )
                    log(f"  [re-sweep] Deleting recreated RDS {db['DBInstanceIdentifier']}")
        except Exception as e:
            log(f"  [re-sweep] RDS: {e}")

        # 16d. CloudFront distribution + VPC origin (recreated by Crossplane)
        try:
            vos = cf.list_vpc_origins().get("VpcOriginList", {}).get("Items", [])
            vo_ids = {vo["Id"] for vo in vos if vo.get("Name", "").startswith(hub + "-")}
            dist_ids = set()
            for d in cf.list_distributions().get("DistributionList", {}).get("Items", []):
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
                    log(f"  [re-sweep] Disabling recreated CF distribution {dist_id}...")
                    poll_until(
                        lambda dist_id=dist_id: cf.get_distribution(Id=dist_id)["Distribution"]["Status"] == "Deployed",
                        attempts=30, delay=15,
                    )
                etag2 = cf.get_distribution(Id=dist_id)["ETag"]
                cf.delete_distribution(Id=dist_id, IfMatch=etag2)
                log(f"  [re-sweep] Deleted recreated CF distribution {dist_id}")
            if dist_ids:
                time.sleep(5)
            for vo_id in vo_ids:
                try:
                    etag = cf.get_vpc_origin(Id=vo_id)["ETag"]
                    cf.delete_vpc_origin(Id=vo_id, IfMatch=etag)
                    log(f"  [re-sweep] Deleted recreated CF VPC origin {vo_id}")
                except Exception:
                    pass
        except Exception as e:
            log(f"  [re-sweep] CloudFront: {e}")

        # 16e. Re-clear leftover SGs in the IDE VPC (recreated / missed by §15)
        if ide_vpc:
            n = _delete_vpc_sgs(ide_vpc)
            if n:
                log(f"  [re-sweep] Cleared {n} more leftover SG(s) in IDE VPC {ide_vpc}")

        # 16f. ENI gate — wait for the service-managed ENIs that block subnet deletion
        #      (cloudfront_managed / amp_collector / RDSNetworkInterface) to detach.
        if ide_vpc:
            def _blocking_enis():
                out = []
                try:
                    for e in ec2.describe_network_interfaces(
                        Filters=[{"Name": "vpc-id", "Values": [ide_vpc]}]
                    )["NetworkInterfaces"]:
                        if e.get("InterfaceType") in ("amp_collector", "cloudfront_managed") \
                           or e.get("Description", "").startswith("RDSNetworkInterface"):
                            out.append(e["NetworkInterfaceId"])
                except Exception:
                    pass
                return out
            # up to ~12 min (36 x 20 s) — RDS ENI release is the long pole.
            _eg = {"i": 0}

            def _enis_cleared():
                b = _blocking_enis()
                if not b:
                    log(f"  [re-sweep] No blocking ENIs left in IDE VPC {ide_vpc}")
                    return True
                if _eg["i"] % 3 == 0:
                    log(f"  [re-sweep] Waiting for {len(b)} blocking ENI(s) to detach from IDE VPC {ide_vpc}...")
                _eg["i"] += 1
                return False

            poll_until(_enis_cleared, attempts=36, delay=20)
        else:
            log("  [re-sweep] IDE VPC not found — skipping final re-sweep")
    except Exception as e:
        log(f"Final re-sweep: {e}")
