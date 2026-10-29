#!/usr/bin/env python3
"""
sweep-hub-leftovers.py PREFIX AWS_REGION HUB [--inventory FILE] [--dry-run [--assume-deleted CLUSTER ...]]

task kind-kro-ack:destroy step 2b, after the hub cluster is deleted. Removes what
the controllers leave behind once the hub is gone, for clusters of THIS stack
(the hub, or <PREFIX>-*) that are no longer live and not retained:
  * EBS volumes in status available tagged kubernetes.io/cluster/<cluster>=owned
    (PVCs of a Retain StorageClass);
  * target groups tagged elbv2.k8s.aws/cluster=<cluster> with no load balancer
    (step 1 deletes the ALBs only);
  * CloudWatch Logs delivery sources and destinations named after the hub that
    no delivery uses any more (step 2 deletes the deliveries only).
Never fails destroy (exit 0); errors print the AWS error code only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, ec2=None, elbv2=None, logs=None, eks=None, out=sys.stdout):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 3 or not all(pos[:3]):
        print(__doc__, file=sys.stderr)
        return 2
    prefix, region, hub = pos[:3]
    try:
        if None in (ec2, elbv2, logs, eks):
            import boto3
            ec2 = ec2 or boto3.client('ec2', region_name=region)
            elbv2 = elbv2 or boto3.client('elbv2', region_name=region)
            logs = logs or boto3.client('logs', region_name=region)
            eks = eks or boto3.client('eks', region_name=region)
        clusters = sl.cluster_inventory(eks)
    except Exception as e:
        print(f'  ⚠ cannot read the EKS clusters ({sl.err_code(e)}): hub leftovers not swept', file=out)
        return 0
    try:
        r = sl.sweep_hub_leftovers(ec2, elbv2, logs, prefix, hub, clusters,
                                   sl.load_inventory(o['inventory']), o['dry_run'], o['assume_deleted'])
    except Exception as e:
        print(f'  ⚠ hub leftover sweep stopped ({sl.err_code(e)})', file=out)
        return 0
    total = sum(len(r[k]) for k in ('volumes', 'target_groups', 'delivery_sources', 'delivery_destinations'))
    print(f'  hub leftovers: {total} selected, {r["deleted"]} deleted', file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
