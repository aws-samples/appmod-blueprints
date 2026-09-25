"""Final safety-net reaper (§16b) — tag-driven orphan deletion (appmod-blueprints#924).

Runs AFTER the ordered per-service reapers (§1–§16) and BEFORE the completeness
gate (§17). Enumerates everything still carrying ``platform.gitops.io/prefix=<prefix>``
via the Resource Groups Tagging API and DELETES the out-of-CFN orphans the name/prefix/
cluster scans missed (arbitrarily-named kro/ACK resources). This is a BACKSTOP,
not a replacement for the ordered reapers:

  * it runs LAST, so dependencies torn down by the ordered reapers are already
    gone — a leaf delete here rarely hits DependencyViolation (and VPCs still go
    through the shared dependency-aware ``vpc.reap_single_vpc``);
  * it SKIPS Layer 1 CFN-managed resources (``aws:cloudformation:*`` tag) —
    CloudFormation deletes those itself after the sweep; deleting them here would
    race CFN;
  * it only dispatches deletes for a KNOWN, BOUNDED set of resource types. Anything
    it does not recognise, or cannot delete (AccessDenied), is LEFT for the §17
    gate to report as residue — the net never blind-deletes an unknown ARN.

Idempotent (an already-gone resource is success) and honest (access-denied is
counted and surfaced, never swallowed). The prefix is always set (argv[2]), so the
tag enumeration is always active.
"""

from ..resilience import classify, retry_aws
from . import vpc as vpc_reaper


def _parse_arn(arn):
    """Return (service, resource_type, resource_id) from an ARN.

    ARN grammar: arn:partition:service:region:account:<resource>, where <resource>
    is 'type/id', 'type:id', or a bare 'id'. EC2 uses the clean 'type/id' form
    (vpc/vpc-…, subnet/subnet-…) so per-type dispatch works; services whose ARN
    shape is awkward (logs, secretsmanager, elb, s3) are handled by a (service,'*')
    wildcard handler that re-derives what it needs from the raw ARN.
    """
    parts = arn.split(":", 5)
    if len(parts) < 6:
        return "", "", ""
    service = parts[2]
    resource = parts[5]
    if "/" in resource:
        rtype, rid = resource.split("/", 1)
    elif ":" in resource:
        rtype, rid = resource.split(":", 1)
    else:
        rtype, rid = "", resource
    return service, rtype, rid


# ── per-type delete handlers (raise on real error → classify() decides) ──────────

def _del_eks_cluster(ctx, rid, arn):
    retry_aws(ctx.eks.delete_cluster, name=rid, attempts=3)


def _del_ec2_vpc(ctx, rid, arn):
    # Dependency-aware (shared with §14): clears ENIs/NAT/subnets/SGs then deletes.
    vpc_reaper.reap_single_vpc(ctx, rid)


def _del_ec2_subnet(ctx, rid, arn):
    retry_aws(ctx.ec2.delete_subnet, SubnetId=rid)


def _del_ec2_natgw(ctx, rid, arn):
    retry_aws(ctx.ec2.delete_nat_gateway, NatGatewayId=rid)


def _del_ec2_sg(ctx, rid, arn):
    try:
        sgs = ctx.ec2.describe_security_groups(GroupIds=[rid]).get("SecurityGroups", [])
        if sgs:
            ctx.revoke_sg_rules(sgs[0])
    except Exception:
        pass
    retry_aws(ctx.ec2.delete_security_group, GroupId=rid)


def _del_ec2_eip(ctx, rid, arn):
    # elastic-ip ARN resource id is the AllocationId (eipalloc-…).
    retry_aws(ctx.ec2.release_address, AllocationId=rid)


def _del_ec2_eni(ctx, rid, arn):
    retry_aws(ctx.ec2.delete_network_interface, NetworkInterfaceId=rid)


def _del_ecr_repo(ctx, rid, arn):
    retry_aws(ctx.ecr.delete_repository, repositoryName=rid, force=True)


def _del_rds_db(ctx, rid, arn):
    retry_aws(ctx.rds.delete_db_instance, DBInstanceIdentifier=rid,
              SkipFinalSnapshot=True, DeleteAutomatedBackups=True)


def _del_s3_bucket(ctx, rid, arn):
    # s3 ARN: arn:aws:s3:::<bucket> → bare resource, rid == bucket name.
    bucket = rid or arn.rsplit(":", 1)[-1]
    s3 = ctx.s3
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        batch = [{"Key": o["Key"], "VersionId": o["VersionId"]}
                 for o in (page.get("Versions", []) + page.get("DeleteMarkers", []))]
        for i in range(0, len(batch), 1000):
            try:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": batch[i:i + 1000], "Quiet": True})
            except Exception:
                pass
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        batch = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        for i in range(0, len(batch), 1000):
            try:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": batch[i:i + 1000], "Quiet": True})
            except Exception:
                pass
    retry_aws(ctx.s3.delete_bucket, Bucket=bucket)


def _del_logs_group(ctx, rid, arn):
    # logs ARN: arn:aws:logs:region:acct:log-group:<name>:* → derive the group name.
    name = arn.split(":log-group:", 1)[-1]
    if name.endswith(":*"):
        name = name[:-2]
    retry_aws(ctx.logs.delete_log_group, logGroupName=name)


def _del_secret(ctx, rid, arn):
    retry_aws(ctx.sm.delete_secret, SecretId=arn, ForceDeleteWithoutRecovery=True)


def _del_elb(ctx, rid, arn):
    retry_aws(ctx.elbv2.delete_load_balancer, LoadBalancerArn=arn)


# (service, resource_type) → handler.  '*' matches any resource_type for that
# service (used where the ARN shape doesn't give a clean per-type key).
_HANDLERS = {
    ("eks", "cluster"): _del_eks_cluster,
    ("ec2", "vpc"): _del_ec2_vpc,
    ("ec2", "subnet"): _del_ec2_subnet,
    ("ec2", "natgateway"): _del_ec2_natgw,
    ("ec2", "security-group"): _del_ec2_sg,
    ("ec2", "elastic-ip"): _del_ec2_eip,
    ("ec2", "network-interface"): _del_ec2_eni,
    ("ecr", "repository"): _del_ecr_repo,
    ("rds", "db"): _del_rds_db,
    ("s3", "*"): _del_s3_bucket,
    ("logs", "*"): _del_logs_group,
    ("secretsmanager", "*"): _del_secret,
    ("elasticloadbalancing", "*"): _del_elb,
}


def run(ctx):
    """Delete out-of-CFN orphans still carrying platform.gitops.io/prefix=<prefix>. Returns
    a summary dict {deleted, skipped_cfn, access_denied, unhandled, failed}."""
    log = ctx.log
    summary = {"deleted": 0, "skipped_cfn": 0, "access_denied": 0, "unhandled": 0, "failed": 0}

    # The ordered reapers just deleted most owned resources; re-query live so we
    # act on the CURRENT set, not the cache captured during spoke discovery.
    ctx.invalidate_tag_cache()
    try:
        tagged = ctx.discover_by_tag()
    except Exception as e:
        log(f"Final net: tag enumeration failed ({classify(e)}): {e}")
        return summary

    if not tagged:
        log("Final net: no platform.gitops.io/prefix-tagged resources remain")
        return summary

    for arn, tags in tagged:
        if any(k.startswith("aws:cloudformation:") for k in tags):
            summary["skipped_cfn"] += 1
            continue  # Layer 1 — CloudFormation reaps it after the sweep
        service, rtype, rid = _parse_arn(arn)
        handler = _HANDLERS.get((service, rtype)) or _HANDLERS.get((service, "*"))
        if handler is None:
            summary["unhandled"] += 1
            log(f"  [final-net] unhandled tagged resource, leaving for §17 gate: {arn}")
            continue
        try:
            handler(ctx, rid, arn)
            summary["deleted"] += 1
            log(f"  [final-net] deleted orphan {arn}")
        except Exception as e:
            kind = classify(e)
            if kind == "gone":
                summary["deleted"] += 1  # idempotent delete of an absent resource = success
                log(f"  [final-net] already gone {arn}")
            elif kind == "access_denied":
                summary["access_denied"] += 1
                log(f"  [final-net] ACCESS DENIED deleting {arn}: {e}")
            else:
                summary["failed"] += 1
                log(f"  [final-net] failed ({kind}) {arn}: {e} — leaving for §17 gate")

    # Re-query live again so the §17 gate reflects what the net just deleted.
    ctx.invalidate_tag_cache()
    log(
        f"Final net: deleted {summary['deleted']}, skipped {summary['skipped_cfn']} "
        f"CFN-managed, {summary['access_denied']} access-denied, "
        f"{summary['unhandled']} unhandled, {summary['failed']} failed"
    )
    return summary
