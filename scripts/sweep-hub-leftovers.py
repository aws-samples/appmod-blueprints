#!/usr/bin/env python3
"""
sweep-hub-leftovers.py PREFIX AWS_REGION HUB [--inventory FILE] [--domain D] [--keep-data]
                       [--dry-run [--assume-deleted CLUSTER ...]]

task kind-kro-ack:destroy step 2b, after the hub cluster is deleted. Removes what
the controllers leave behind once the hub is gone, for clusters of THIS stack
(exact names: the hub, the inventory's kro cluster instances, <PREFIX>-spoke-dev
and <PREFIX>-spoke-prod) that are no longer live and not retained:
  * EBS volumes in status available tagged kubernetes.io/cluster/<cluster>=owned
    (PVCs of a Retain StorageClass); kept with --keep-data;
  * target groups tagged elbv2.k8s.aws/cluster=<cluster> with no load balancer
    (step 1 deletes the ALBs only); a delete answered ResourceInUse (the ALB step 1
    just deleted still holds them) is retried, bounded (~3 min);
  * CloudWatch Logs delivery sources and destinations named after the hub that
    no delivery uses any more (step 2 deletes the deliveries only).
Never fails destroy (exit 0); errors print the AWS error code only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, ec2=None, elbv2=None, logs=None, eks=None, out=sys.stdout, r53=None):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 3 or not all(pos[:3]):
        print(__doc__, file=sys.stderr)
        return 2
    prefix, region, hub = pos[:3]
    try:
        if None in (ec2, elbv2, logs, eks):
            ec2 = ec2 or sl.client('ec2', region)
            elbv2 = elbv2 or sl.client('elbv2', region)
            logs = logs or sl.client('logs', region)
            eks = eks or sl.client('eks', region)
            if r53 is None and o['domain']:
                r53 = sl.client('route53', region)
        clusters = sl.cluster_inventory(eks)
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  ⚠ cannot read the EKS clusters ({sl.err_code(e)}): hub leftovers not swept', file=out)
        return 0
    try:
        r = sl.sweep_hub_leftovers(ec2, elbv2, logs, prefix, hub, clusters,
                                   sl.load_inventory(o['inventory']), o['dry_run'], o['assume_deleted'],
                                   r53=r53, domain=o['domain'], keep_data=o['keep_data'])
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  ⚠ hub leftover sweep stopped ({sl.err_code(e)})', file=out)
        return 0
    total = sum(len(r[k]) for k in ('volumes', 'target_groups', 'delivery_sources', 'delivery_destinations',
                                         'dns_records'))
    print(f'  hub leftovers: {total} selected, {r["deleted"]} deleted', file=out)
    return 0


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-hub-leftovers'))
