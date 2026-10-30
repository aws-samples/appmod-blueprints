#!/usr/bin/env python3
"""
sweep-iam-guard.py AWS_REGION [--dry-run --assume-deleted CLUSTER ...]
Prints, one per line, the IAM role names that a live EKS cluster in any enabled
region (IAM is global; AWS_REGION is always included) still references: cluster role, access entries, capability roles and pod identity
associations. task kind-kro-ack:destroy (steps 3 and 6b) skips these roles, so
tearing down one hub never deletes the roles another live cluster depends on
(for example a spoke kept with deletionPolicy=retain, whose access entries hold
the hub's management and Argo CD capability roles).

Exits non-zero when the clusters of any region cannot be read; destroy then skips the role
sweep (fail closed) instead of deleting blind.
"""
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, eks=None, out=sys.stdout, ec2=None, eks_for=None):
    pos, o = sl.parse_common(argv, __doc__)
    if not pos or not pos[0]:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        eks_for, regions = sl.guard_regions(pos[0], ec2=ec2, eks=eks, eks_for=eks_for)
        roles = sl.protected_roles_all_regions(pos[0], eks_for, regions, o['assume_deleted'])
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'sweep-iam-guard: {e}', file=sys.stderr)
        return 1
    for r in sorted(roles):
        print(r, file=out)
    return 0


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-iam-guard'))
