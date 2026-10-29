#!/usr/bin/env python3
"""
sweep-rds.py RESOURCE_PREFIX AWS_REGION [--dry-run] [--no-wait]
Deletes the DevLake databases of one deployment (task kind-kro-ack:destroy 6eii):
  * <prefix>-devlake-* Aurora clusters, their instances and DB subnet groups
    (kro RelationalDatabase RGD), skipping the final snapshot;
  * standalone devlake-* instances (legacy KubeVela path), as before.
Resources with DeletionProtection on are reported and left alone.
By default it waits (bounded) for the deletions to finish, because the database
ENIs sit in the hub VPC and would otherwise block sweep-hub-vpc.py.
"""
import os
import sys

import boto3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, rds=None, sleep=None):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 2 or not pos[0]:
        sl.log(__doc__)
        return 2
    prefix, region = pos[:2]
    rds = rds or boto3.client('rds', region_name=region)
    kw = {'sleep': sleep} if sleep else {}
    try:
        return sl.sweep_rds(rds, prefix, dry_run=o['dry_run'], wait=not o['no_wait'], **kw)
    except Exception as e:
        sl.log(f'  ⚠ RDS sweep failed ({sl.err_code(e)}); DevLake databases not cleaned')
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
