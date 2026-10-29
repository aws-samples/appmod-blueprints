#!/usr/bin/env python3
"""
sweep-hub-vpc.py RESOURCE_PREFIX AWS_REGION HUB_CLUSTER_NAME
                 [--inventory FILE] [--dry-run [--assume-deleted CLUSTER ...]]
Deletes the hub's own VPC (NAT gateways + EIPs, IGW, endpoints, subnets, route
tables, security groups) once the hub EKS cluster is gone.
Called by task kind-kro-ack:destroy step 6h2.

Why it is needed: on kind-kro-ack the hub EksclusterWithVpc is created on kind with
deletionPolicy=retain, kind is deleted before anything could gracefully delete that
instance, and destroy removes the hub cluster through the AWS API. Nothing deleted
the VPC kro/ACK built for it, and sweep-spoke-vpcs.py excludes the hub on purpose.

Candidates: the VPC id destroy recorded from the hub cluster before deleting it
(inventory hub_vpc_id), and any VPC tagged platform.gitops.io/prefix=<prefix> AND
platform.gitops.io/cluster=<hub>. Never swept: a CloudFormation-owned VPC (in the
workshop the hub runs in the IDE VPC, which the stack deletes), a VPC without
exactly this prefix tag, a VPC that still hosts a live EKS cluster (including the
hub itself, if its deletion failed).
"""
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, ec2=None, eks=None):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 3 or not all(pos[:3]):
        sl.log(__doc__)
        return 2
    prefix, region, hub = pos[:3]
    ec2 = ec2 or sl.client('ec2', region)
    eks = eks or sl.client('eks', region)
    try:
        clusters = sl.cluster_inventory(eks)
    except Exception as e:
        sl.reraise_credentials(e)
        sl.log(f'  ⚠ cannot list EKS clusters ({e}); not sweeping the hub VPC')
        return 1
    inv = sl.load_inventory(o['inventory'])
    try:
        selected, skipped = sl.select_hub_vpc(ec2, prefix, hub, clusters, inv, o['assume_deleted'])
        return 1 if sl.run_vpc_sweep(ec2, 'hub', selected, skipped, o['dry_run']) else 0
    except Exception as e:
        sl.reraise_credentials(e)
        sl.log(f'  ⚠ hub VPC sweep failed ({sl.err_code(e)})')
        return 1


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-hub-vpc'))
