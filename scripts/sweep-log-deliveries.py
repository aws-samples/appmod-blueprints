#!/usr/bin/env python3
"""
sweep-log-deliveries.py PREFIX AWS_REGION HUB [--inventory FILE]
                        [--dry-run [--assume-deleted CLUSTER ...]]

task kind-crossplane:destroy, after the hub cluster is deleted (kind-kro-ack runs the
same sweep inside sweep-hub-leftovers.py, step 2b). Deletes the CloudWatch Logs
capability-log objects the root `task enable-capability-logs` creates for every
cluster: delivery source <cluster>-<cap>, destination <cluster>-<cap>-cwl, and the
delivery between them, for the removed clusters of THIS stack only (exact names: the
hub, the inventory's spokes, PREFIX-spoke-dev/-prod; not live, not retained; never a
PREFIX-* pattern). Deliveries first, then sources, then destinations.
Never fails destroy (exit 0); errors print the AWS error code only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, eks=None, logs=None, out=sys.stdout):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 3 or not all(pos[:3]):
        print(__doc__, file=sys.stderr)
        return 2
    prefix, region, hub = pos[:3]
    inventory = sl.load_inventory(o['inventory'])
    try:
        eks = eks or sl.client('eks', region)
        clusters = sl.cluster_inventory(eks)
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  ⚠ cannot read the EKS clusters ({sl.err_code(e)}): log deliveries not swept', file=out)
        return 0
    is_gone = sl.gone_stack_clusters(prefix, hub, clusters, inventory, o['assume_deleted'])
    gone = {c for c in sl.stack_cluster_names(prefix, hub, inventory) if is_gone(c)}
    try:
        logs = logs or sl.client('logs', region)
        ids, srcs, dsts, n = sl.sweep_log_deliveries(logs, gone, o['dry_run'])
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  ⚠ log delivery sweep stopped ({sl.err_code(e)})', file=out)
        return 0
    print(f'  log deliveries: {len(ids) + len(srcs) + len(dsts)} selected, {n} deleted', file=out)
    return 0


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-log-deliveries'))
