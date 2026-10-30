#!/usr/bin/env python3
"""
sweep-shared-iam.py AWS_REGION --inventory FILE [--dry-run]

task kind-kro-ack:destroy step 6b2, after the hub is deleted. Deletes the
fixed-name IAM roles that protect-shared-iam.py retained (recorded in
shared-iam-retained.json next to the inventory) once NO live EKS cluster in ANY
enabled region references them any more: IAM is global, so a hub in another
region that uses the same fixed-name role keeps it. A role another live cluster
still uses (pod identity association, access entry, capability, cluster role) is
kept. If any region's clusters cannot be read, nothing is deleted (fail closed)
and the step is recorded in destroy-sweep-failures. A hub that recreates the role later (its own managed
resource) does so on its next reconcile.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, eks=None, iam=None, out=sys.stdout, ec2=None, eks_for=None):
    pos, o = sl.parse_common(argv, __doc__)
    if not pos or not pos[0] or not o['inventory']:
        print(__doc__, file=sys.stderr)
        return 2
    names = sl.load_shared_roles(sl.shared_roles_record_path(o['inventory']))
    if not names:
        print('  no shared IAM role recorded: nothing to sweep', file=out)
        return 0
    try:
        iam = iam or sl.client('iam', pos[0])
        eks_for, regions = sl.guard_regions(pos[0], ec2=ec2, eks=eks, eks_for=eks_for)
        protected = sl.protected_roles_all_regions(pos[0], eks_for, regions, o['assume_deleted'])
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  WARN cannot read the live EKS clusters of every enabled region ({sl.err_code(e)}): '
              f'keeping the shared role(s) {", ".join(names)} (fail closed)', file=out)
        # Not deleted means left behind: destroy's final check must not print success.
        sl.record_failure('sweep-shared-iam(guard)')
        return 0
    deleted, kept = sl.sweep_shared_roles(iam, names, protected, o['dry_run'])
    print(f'  shared IAM roles: {len(deleted)} {"to delete" if o["dry_run"] else "deleted"}, '
          f'{len(kept)} kept', file=out)
    return 0


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-shared-iam'))
