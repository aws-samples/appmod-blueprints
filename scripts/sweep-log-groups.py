#!/usr/bin/env python3
"""
sweep-log-groups.py RESOURCE_PREFIX AWS_REGION HUB_CLUSTER_NAME
                    [--inventory FILE] [--dry-run [--assume-deleted CLUSTER ...]]
Deletes the /aws/eks/<cluster>/... CloudWatch log groups of the clusters this
destroy removed (task kind-kro-ack:destroy 6g), by exact cluster name: the hub,
the spokes the inventory lists (any name), <prefix>-spoke-dev and
<prefix>-spoke-prod. Never a <prefix>-* wildcard, which would also take the
groups of a stack whose prefix starts with ours. A group is kept while its cluster still exists and is not DELETING,
or when the inventory marks the cluster as retained.
"""
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, logs=None, eks=None):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 3 or not pos[0]:
        sl.log(__doc__)
        return 2
    prefix, region, hub = pos[:3]
    logs = logs or sl.client('logs', region)
    eks = eks or sl.client('eks', region)
    try:
        clusters = sl.cluster_inventory(eks)
    except Exception as e:
        sl.reraise_credentials(e)
        sl.log(f'  ⚠ cannot list EKS clusters ({e}); not sweeping log groups')
        return 1
    inv = sl.load_inventory(o['inventory'])
    try:
        selected, skipped = sl.select_log_groups(logs, prefix, hub, clusters, inv, o['assume_deleted'])
        return sl.sweep_log_groups(logs, selected, skipped, o['dry_run'])
    except Exception as e:
        sl.reraise_credentials(e)
        sl.log(f'  ⚠ log-group sweep failed ({sl.err_code(e)})')
        return 1


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-log-groups'))
