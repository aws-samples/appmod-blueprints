#!/usr/bin/env python3
"""
sweep-spoke-vpcs.py RESOURCE_PREFIX AWS_REGION [HUB_CLUSTER_NAME]
                    [--inventory FILE] [--dry-run [--assume-deleted CLUSTER ...]]
Deletes orphaned spoke VPCs left behind after the spoke clusters are gone.
Called by task kind-kro-ack:destroy step 6h.

Selects by OWNERSHIP TAG, not by name. Spoke names are arbitrary, so the previous
filter — the two literal values <prefix>-spoke-dev-vpc and <prefix>-spoke-prod-vpc —
could not see a spoke called anything else (including a conforming third one such as
<prefix>-spoke-staging). The legacy names are still included, so a pre-tag install
sweeps exactly what it swept before.

HUB_CLUSTER_NAME should be passed: the hub carries the same ownership tag, and its VPC
is swept separately (sweep-hub-vpc.py) only once the hub cluster is gone. It cannot
be derived as <prefix>-hub, because cluster names are arbitrary.

Never swept (see sweep_lib.py): a CloudFormation-owned VPC (the workshop IDE/hub VPC),
a VPC whose prefix tag is not exactly RESOURCE_PREFIX, a VPC that still hosts an EKS
cluster which is not DELETING (e.g. a spoke kept by deletionPolicy=retain), and a VPC
tagged for a cluster the destroy inventory lists as retained.
"""
import os
import sys

import boto3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, ec2=None, eks=None):
    pos, o = sl.parse_common(argv, __doc__)
    prefix = pos[0] if len(pos) > 0 else 'peeks'
    region = pos[1] if len(pos) > 1 else 'us-west-2'
    hub = pos[2] if len(pos) > 2 else ''
    ec2 = ec2 or boto3.client('ec2', region_name=region)
    eks = eks or boto3.client('eks', region_name=region)
    try:
        clusters = sl.cluster_inventory(eks)
    except Exception as e:
        # Fail closed: without the cluster list we cannot tell a live VPC from an orphan.
        sl.log(f'  ⚠ cannot list EKS clusters ({e}); not sweeping spoke VPCs')
        return 1
    inv = sl.load_inventory(o['inventory'])
    try:
        selected, skipped = sl.select_spoke_vpcs(ec2, prefix, hub, clusters, inv, o['assume_deleted'])
        return 1 if sl.run_vpc_sweep(ec2, 'spoke', selected, skipped, o['dry_run']) else 0
    except Exception as e:
        sl.log(f'  ⚠ spoke VPC sweep failed ({sl.err_code(e)})')
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
