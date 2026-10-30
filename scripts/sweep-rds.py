#!/usr/bin/env python3
"""
sweep-rds.py RESOURCE_PREFIX AWS_REGION [--dry-run] [--no-wait] [--keep-data]
Deletes the DevLake databases of one deployment (task kind-kro-ack:destroy 6eii):
  * <prefix>-devlake-* Aurora clusters, their instances and DB subnet groups
    (kro RelationalDatabase RGD), skipping the final snapshot;
  * standalone devlake-* instances (legacy KubeVela path), as before.
Resources with DeletionProtection on are reported and left alone.
--keep-data (DESTROY_KEEP_DATA=true) takes a final snapshot of each cluster and
standalone instance before the delete.
By default it waits (bounded) for the deletions to finish, because the database
ENIs sit in the hub VPC and would otherwise block sweep-hub-vpc.py.
"""
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, rds=None, sleep=None):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 2 or not pos[0]:
        sl.log(__doc__)
        return 2
    prefix, region = pos[:2]
    rds = rds or sl.client('rds', region)
    kw = {'sleep': sleep} if sleep else {}
    try:
        return sl.sweep_rds(rds, prefix, dry_run=o['dry_run'], wait=not o['no_wait'],
                            keep_data=o['keep_data'], **kw)
    except Exception as e:
        sl.reraise_credentials(e)
        sl.log(f'  ⚠ RDS sweep failed ({sl.err_code(e)}); DevLake databases not cleaned')
        return 1


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-rds'))
