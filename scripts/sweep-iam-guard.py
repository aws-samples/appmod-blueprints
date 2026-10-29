#!/usr/bin/env python3
"""
sweep-iam-guard.py AWS_REGION [--dry-run --assume-deleted CLUSTER ...]
Prints, one per line, the IAM role names that a live EKS cluster in AWS_REGION
still references: cluster role, access entries, capability roles and pod identity
associations. task kind-kro-ack:destroy (steps 3 and 6b) skips these roles, so
tearing down one hub never deletes the roles another live cluster depends on
(for example a spoke kept with deletionPolicy=retain, whose access entries hold
the hub's management and Argo CD capability roles).

Exits non-zero when the clusters cannot be read; destroy then skips the role
sweep (fail closed) instead of deleting blind.
"""
import os
import sys

import boto3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, eks=None, out=sys.stdout):
    pos, o = sl.parse_common(argv, __doc__)
    if not pos or not pos[0]:
        print(__doc__, file=sys.stderr)
        return 2
    eks = eks or boto3.client('eks', region_name=pos[0])
    try:
        clusters = sl.cluster_inventory(eks)
        roles = sl.protected_roles(eks, clusters, o['assume_deleted'])
    except Exception as e:
        print(f'sweep-iam-guard: {e}', file=sys.stderr)
        return 1
    for r in sorted(roles):
        print(r, file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
