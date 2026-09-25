"""Sweep orchestrator (issue #924, principle #2).

Builds the SweepContext then runs every per-service reaper in the EXACT original
order — the order is load-bearing (load balancers before EIPs before the VPC
reaper; the re-sweep after the hub/spoke clusters are gone). Returns the process
exit code: non-zero when owned resources remain (unless SWEEP_ALLOW_RESIDUE), so a
strict caller can surface an incomplete teardown; the CFN Delete path runs the
sweep with `|| true`, so the IDE-VPC deletion is never blocked by this.
"""

import os

from .context import SweepContext
from .reapers import (
    amp,
    cloudfront,
    ecr,
    eip,
    eks,
    elb,
    grafana,
    iam,
    logs,
    rds,
    resweep,
    s3,
    secrets,
    verify,
    vpc,
)


def main(region="us-west-2", prefix="peeks"):
    ctx = SweepContext(region, prefix)

    eks.reap_capabilities(ctx)        # 1.   EKS capabilities
    cloudfront.reap(ctx)              # 2.   CloudFront VPC origin + distribution
    elb.reap_prefixed(ctx)            # 3.   Prefixed ALBs
    rds.reap(ctx)                     # 4.   RDS (DevLake)
    amp.reap(ctx)                     # 5.   AMP scrapers + workspaces
    eks.reap_hub(ctx)                 # 6.   Hub EKS cluster (sets ctx.hub_vpc_id)
    eks.reap_orphan_spokes(ctx)       # 6b.  Orphaned spoke EKS clusters
    iam.reap(ctx)                     # 7.   IAM roles + customer-managed policies
    secrets.reap(ctx)                 # 8.   Secrets Manager
    ecr.reap(ctx)                     # 8b.  ECR (Ray/vLLM repo)
    s3.reap(ctx)                      # 8c.  S3 (Ray model cache + deploy staging)
    logs.reap_log_groups(ctx)         # 9.   CloudWatch log groups
    vpc.reap_spoke_vpcs(ctx)          # 10.  Spoke VPCs
    grafana.reap(ctx)                 # 11.  AMG workspaces
    logs.reap_deliveries(ctx)         # 12.  CloudWatch Logs deliveries
    elb.reap_controller_lbs(ctx)      # 12b. AWS-LB-Controller LBs (before EIP/VPC)
    eip.reap(ctx)                     # 13.  Orphaned Elastic IPs
    vpc.reap_guardduty_endpoints(ctx)  # 13b. GuardDuty VPC endpoints (before VPC reaper)
    vpc.reap_orphan_vpcs(ctx)         # 14.  Orphan VPC reaper (backstop for 10)
    vpc.reap_ide_sgs(ctx)             # 15.  Leftover SGs in the IDE VPC
    vpc.reap_guardduty_sgs(ctx)       # 15b. GuardDuty-managed SGs
    resweep.run(ctx)                  # 16.  Final re-sweep of recreatable resources + ENI gate
    residue = verify.run(ctx)         # 17.  Completeness verification + re-drive

    ctx.log("Extended sweep complete.")

    if residue and os.environ.get("SWEEP_ALLOW_RESIDUE", "").lower() not in ("1", "true", "yes"):
        return 1
    return 0
