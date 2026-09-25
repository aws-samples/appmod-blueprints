#!/usr/bin/env python3
"""
sweep-workshop-resources.py — Extended AWS resource sweep for workshop teardown.

Called by the ClustersStackDeploy CodeBuild after `workshop/task destroy` completes,
to remove resources that persist after task destroy and would block VPC subnet
deletion when CloudFormation tries to clean up the IDE VPC.

Usage:
    python3 sweep-workshop-resources.py <region> <resource_prefix> [stack_name]

    region          AWS region (e.g. us-west-2)
    resource_prefix Workshop resource prefix (e.g. peeks)
    stack_name      Optional peeks.io tag value (CFN stack name). Also read from the
                    PLATFORM_STACK_NAME env var. When set, the sweep additionally
                    enumerates resources by peeks.io=<stack_name> (Resource Groups
                    Tagging API) for an authoritative completeness gate. Unset ->
                    prefix/cluster-tag discovery only (unchanged behaviour).

The heavy lifting lives in the `sweep/` package (issue #924, principle #2):
    sweep/context.py      shared boto3 clients + state + VPC/SG helpers
    sweep/resilience.py   tenacity-backed retry/poll + AWS error classification
    sweep/reapers/*.py    one module per service (EKS, CloudFront, ELB, RDS, AMP,
                          IAM, Secrets, ECR, S3, CloudWatch Logs, VPC, EIP, Grafana),
                          plus resweep.py (§16) and verify.py (§17)
    sweep/orchestrator.py runs every reaper in the load-bearing original order

Exit code: non-zero when owned resources remain (unless SWEEP_ALLOW_RESIDUE) so a
strict caller can surface an incomplete teardown. The CFN Delete path invokes the
sweep with `|| true`, so the IDE-VPC deletion is NEVER blocked by residue.
"""

import os
import sys

# The sweep/ package lives next to this entrypoint; add that dir to sys.path so the
# import resolves regardless of the caller's CWD.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sweep.orchestrator import main  # noqa: E402

if __name__ == "__main__":
    region = sys.argv[1] if len(sys.argv) > 1 else "us-west-2"
    prefix = sys.argv[2] if len(sys.argv) > 2 else "peeks"
    # peeks.io=<stack> deployment tag value: PLATFORM_STACK_NAME (exported by the
    # ClustersStackDeploy build = CFN ${AWS::StackName}), or an optional 3rd arg.
    # Unset -> tag-based discovery/gate is skipped (prefix/cluster discovery only).
    stack_name = os.environ.get("PLATFORM_STACK_NAME") or (sys.argv[3] if len(sys.argv) > 3 else None)
    sys.exit(main(region, prefix, stack_name))
