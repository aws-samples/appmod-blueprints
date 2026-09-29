"""Elastic Load Balancing reapers: prefixed ALBs (§3) and AWS-LB-Controller LBs (§12b).

`lb_owned` is the shared ownership predicate, reused by the §16 re-sweep — which
removes the old NameError-fallback hack that duplicated it inline.
"""

import time


def lb_owned(ctx, arn, name):
    """True if a load balancer / target group is workshop-owned: <prefix>-* name,
    OR the AWS LB Controller tag elbv2.k8s.aws/cluster in {hub, spokes}, OR the
    #914 ownership tag."""
    prefix, elbv2, OWNER_PREFIX_TAG = ctx.prefix, ctx.elbv2, ctx.OWNER_PREFIX_TAG
    owned_clusters = {ctx.hub, *ctx.spokes}
    if name.startswith(prefix + "-"):
        return True
    try:
        td = {
            t["Key"]: t["Value"]
            for t in elbv2.describe_tags(ResourceArns=[arn])["TagDescriptions"][0]["Tags"]
        }
    except Exception:
        return False
    return td.get("elbv2.k8s.aws/cluster") in owned_clusters or td.get(OWNER_PREFIX_TAG) == prefix


def reap_prefixed(ctx):
    """§3. The hub platform ALB (<prefix>-hub-platform) creates ENIs in IDE VPC subnets."""
    log, elbv2, prefix = ctx.log, ctx.elbv2, ctx.prefix
    try:
        deleted = 0
        for lb in elbv2.describe_load_balancers()["LoadBalancers"]:
            if lb["LoadBalancerName"].startswith(prefix + "-"):
                elbv2.delete_load_balancer(LoadBalancerArn=lb["LoadBalancerArn"])
                log(f"  Deleted ALB {lb['LoadBalancerName']}")
                deleted += 1
        if not deleted:
            log("No ALBs to delete")
    except Exception as e:
        log(f"ALBs: {e}")


def reap_controller_lbs(ctx):
    """§12b. LBs created by the AWS Load Balancer Controller (k8s-<ns>-<name>-<hash>)
    that do NOT start with the prefix. They hold ServiceManaged EIPs + amazon-elb
    ENIs that block the VPC reap, so run this BEFORE the EIP and VPC-reaper sections."""
    log, elbv2 = ctx.log, ctx.elbv2
    try:
        reaped_lb = 0
        lbs = []
        for page in elbv2.get_paginator("describe_load_balancers").paginate():
            lbs.extend(page.get("LoadBalancers", []))
        for lb in lbs:
            if not lb_owned(ctx, lb["LoadBalancerArn"], lb["LoadBalancerName"]):
                continue
            try:
                elbv2.delete_load_balancer(LoadBalancerArn=lb["LoadBalancerArn"])
                reaped_lb += 1
                log(f"  Deleted load balancer {lb['LoadBalancerName']}")
            except Exception as e:
                log(f"  LB {lb['LoadBalancerName']}: {e}")

        # Orphaned target groups (LB controller tags them the same way)
        for page in elbv2.get_paginator("describe_target_groups").paginate():
            for tg in page.get("TargetGroups", []):
                if not lb_owned(ctx, tg["TargetGroupArn"], tg["TargetGroupName"]):
                    continue
                try:
                    elbv2.delete_target_group(TargetGroupArn=tg["TargetGroupArn"])
                except Exception:
                    pass

        if reaped_lb:
            log(f"Load balancers: deleted {reaped_lb}")
            time.sleep(20)  # let ServiceManaged EIPs release + amazon-elb ENIs detach
        else:
            log("No orphaned load balancers to delete")
    except Exception as e:
        log(f"Load balancers: {e}")
