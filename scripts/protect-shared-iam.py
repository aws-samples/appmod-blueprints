#!/usr/bin/env python3
"""
protect-shared-iam.py PREFIX AWS_REGION HUB [--inventory FILE] [--dry-run]

Run by task kind-kro-ack:destroy (hub:destroy-addons step 0), on the hub
kubeconfig ($KUBECONFIG), BEFORE any addon is removed.

Lists the IAM managed resources on the hub (Crossplane v1/v2 Role, Policy and
RolePolicyAttachment; ACK Role and Policy) and marks retain/Orphan every one
this teardown must not delete in AWS:
  * its AWS name is outside PREFIX- (a fixed-name role a chart creates on every
    hub, shared by all of them), or
  * the role is still referenced by a live EKS cluster that is not part of this
    stack (cluster role, access entry, capability, pod identity association).
    "This stack" is HUB plus the spokes the inventory records with
    deletionPolicy=delete; a retained spoke counts as outside.
If the EKS reference check fails, every role CR is retained (fail closed); the
prefix-scoped role sweep of steps 3/6b still deletes this stack's own roles,
behind its own reference guard.

Retaining only makes the controller forget the AWS object when its CR goes away:
nothing is deleted or changed in AWS. --dry-run prints the plan and patches
nothing. Exits 0 even when the hub is unreachable (nothing to protect then).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def run_kubectl(args):
    p = subprocess.run([os.environ.get('KUBECTL', 'kubectl')] + args,
                       capture_output=True, text=True)
    return p.returncode, p.stdout


def list_iam_crs(kubectl):
    out = {}
    for resource in sl.IAM_CR_KINDS:
        rc, txt = kubectl(['get', resource, '-A', '-o', 'json'])
        if rc != 0:
            continue  # CRD not installed on this hub
        try:
            items = json.loads(txt or '{}').get('items', [])
        except ValueError:
            continue
        if items:
            out[resource] = items
    return out


def main(argv, eks=None, kubectl=None, out=sys.stdout):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 3 or not all(pos[:3]):
        print(__doc__, file=sys.stderr)
        return 2
    prefix, region, hub = pos[:3]
    kubectl = kubectl or run_kubectl
    items = list_iam_crs(kubectl)
    if not items:
        print('  no IAM managed resources on the hub (or hub unreachable): nothing to protect', file=out)
        return 0
    inv = sl.load_inventory(o['inventory'])
    own = {hub} | sl.deleted_clusters(inv)
    guard_ok, protected = True, set()
    try:
        if eks is None:
            import boto3
            eks = boto3.client('eks', region_name=region)
        protected = sl.protected_roles(eks, sl.cluster_inventory(eks), assume_deleted=own)
    except Exception as e:
        guard_ok = False
        print(f'  WARN reference check failed ({sl.err_code(e) or type(e).__name__}): '
              'retaining every role CR (fail closed)', file=out)
    retain, delete = sl.select_shared_iam_crs(items, prefix, protected, guard_ok)
    shared = sorted({aws for resource, _, _, aws, why, _ in retain
                     if resource.startswith('roles.') and why.startswith('not owned') and aws})
    if shared and o['inventory'] and not o['dry_run']:
        path = sl.shared_roles_record_path(o['inventory'])
        known = set(sl.load_shared_roles(path))
        try:
            with open(path, 'w') as f:
                json.dump({'roles': sorted(known | set(shared))}, f)
        except OSError as e:
            print(f'  WARN could not record shared roles in {path} ({e})', file=out)
    failed = 0
    for resource, ns, name, aws, why, done in retain:
        where = f'{ns}/{name}' if ns else name
        if done:
            print(f'  keep {resource} {where} -> {aws}: already retained ({why})', file=out)
            continue
        verb = 'would retain' if o['dry_run'] else 'retain'
        print(f'  {verb} {resource} {where} -> {aws}: {why}', file=out)
        if o['dry_run']:
            continue
        args = sl.retain_patch(sl.IAM_CR_KINDS[resource][1])
        cmd = [args[0], resource, name] + (['-n', ns] if ns else []) + args[1:]
        rc, _ = kubectl(cmd)
        if rc != 0:
            failed += 1
            print(f'  ERROR could not retain {resource} {name}', file=out)
    print(f'  {len(retain)} IAM managed resource(s) retained, {len(delete)} left to their '
          f'controller (owned by {prefix}-, not used outside this stack)', file=out)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
