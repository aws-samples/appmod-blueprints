#!/usr/bin/env python3
"""
stack-clusters.py PREFIX HUB [--inventory FILE]
Prints, one per line, the EKS cluster names that belong to THIS stack and that
destroy removes: the hub, every kro cluster instance the teardown inventory
recorded, and the legacy <prefix>-spoke-dev/-prod spokes (sweep_lib's
stack_cluster_names), minus the spokes kept with deletionPolicy=retain.

task kind-kro-ack:destroy step 1 deletes the ALBs whose elbv2.k8s.aws/cluster
tag is one of these exact names, never a <prefix>-* wildcard: destroying prefix
"peeks" must not delete the ALBs of a live "peeks-a-hub" in the same account.
Reads only the inventory file; no AWS call.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, out=sys.stdout):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 2 or not all(pos[:2]):
        print(__doc__, file=sys.stderr)
        return 2
    prefix, hub = pos[:2]
    inv = sl.load_inventory(o['inventory'])
    for name in sorted(sl.stack_cluster_names(prefix, hub, inv) - sl.retained_clusters(inv)):
        print(name, file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
