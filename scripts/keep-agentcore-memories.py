#!/usr/bin/env python3
"""
keep-agentcore-memories.py [--dry-run]

Run by task kind-kro-ack:hub:destroy-addons (step 6b) when DESTROY_KEEP_DATA=true, on the
hub kubeconfig ($KUBECONFIG), right BEFORE step 6c (drain-oam-apps.py).

An AgentCore memory holds the agent's session and long-term memory, and DeleteMemory
cannot be undone. Its Crossplane bedrockagentcore Memory CR (v1 cluster-scoped, v2
namespaced) has the default deletion policy, so step 6c, which deletes the OAM apps while
the provider is still running, makes the provider call DeleteMemory. This step marks every
Memory CR retain/Orphan first, the same patch protect-shared-iam.py uses for IAM resources
(sweep_lib.retain_patch): Crossplane v1 gets deletionPolicy=Orphan, v2 loses Delete from
managementPolicies. Deleting the CR then only makes the controller forget the memory;
nothing is deleted or changed in AWS. The memory ids were recorded at the start of destroy
(record-app-resources.py), so step 2c (sweep-app-resources.py --keep-data) lists them as kept.

A CR that already keeps its AWS object is left as it is. Exits 0 when the hub is
unreachable or has no Memory CR (nothing to keep). Exits 1 when a CR could not be marked:
the caller must then NOT go on to step 6c, which would delete that memory.
--dry-run prints the plan and patches nothing.

shortcut: a v1 Memory with a custom managementPolicies that still holds Delete ignores
deletionPolicy (Crossplane: the management policy wins); the OAP agentcore-memory
component sets none, so this is not handled. Upgrade when it does.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402

MEMORY_KINDS = {r: fam for r, (fam, key) in sl.APP_KINDS.items() if key == 'agentcore_memories'}


def run_kubectl(args):
    p = subprocess.run([os.environ.get('KUBECTL', 'kubectl')] + args,
                       capture_output=True, text=True)
    return p.returncode, p.stdout


def main(argv, kubectl=None, out=sys.stdout):
    _, o = sl.parse_common(argv, __doc__)
    kubectl = kubectl or run_kubectl
    seen = failed = 0
    for resource, family in MEMORY_KINDS.items():
        rc, txt = kubectl(['get', resource, '-A', '-o', 'json'])
        if rc != 0:
            continue  # CRD not installed on this hub, or hub unreachable
        try:
            items = json.loads(txt or '{}').get('items', [])
        except ValueError:
            continue
        for it in items:
            meta = it.get('metadata') or {}
            name, ns = meta.get('name', ''), meta.get('namespace', '')
            where = f'{ns}/{name}' if ns else name
            seen += 1
            if sl.already_retained(family, it):
                print(f'  keep {resource} {where}: already retained', file=out)
                continue
            print(f'  {"would retain" if o["dry_run"] else "retain"} {resource} {where}: '
                  f'DESTROY_KEEP_DATA=true', file=out)
            if o['dry_run']:
                continue
            args = sl.retain_patch(family)
            cmd = [args[0], resource, name] + (['-n', ns] if ns else []) + args[1:]
            if kubectl(cmd)[0] != 0:
                failed += 1
                print(f'  ERROR could not retain {resource} {where}: its memory would be deleted', file=out)
    if not seen:
        print('  no AgentCore Memory CR on the hub (or hub unreachable): nothing to keep', file=out)
    elif failed:
        print(f'  ERROR {failed} of {seen} AgentCore Memory CR(s) not retained', file=out)
    else:
        print(f'  {seen} AgentCore Memory CR(s) kept: deleting the CR leaves the memory in AWS', file=out)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
