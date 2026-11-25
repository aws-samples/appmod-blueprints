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

A CR that already keeps its AWS object is left as it is. Every CR is re-read after the
patch and must really keep its AWS object, or it counts as not retained. This step fails
closed (exit 1, the caller must NOT go on to step 6c, which would delete that memory) when:
  - a `get` fails for any reason other than "this CRD is not installed" (retried once;
    when the hub then answers /readyz the failure is real, when it does not the hub is
    gone and 6c cannot act either, so exit 0 with a warning);
  - a patch fails, or does not take effect (a v1 CR whose explicit managementPolicies holds
    Delete ignores deletionPolicy, so those are patched too, then re-read);
  - the CR is composed by a Crossplane composite (label crossplane.io/composite or a
    controller ownerReference). The crossplane-agentcore AgentCoreMemory Composition sets
    deletionPolicy: Delete on the Memory it composes, so the composite reconciler reverts
    the patch; no patch here can hold. The durable fix is in that Composition (OAP).
MemoryStrategy CRs are retained like the Memory CRs: deleting one makes the provider call
DeleteMemoryStrategy on a memory this step keeps.
--dry-run prints the plan and patches nothing.

shortcut: the composite guard is by label/ownerReference, not by reading the Composition,
so a composite whose Composition does not force Delete is also refused. Upgrade when the OAP
Composition honours a retain setting.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402

MEMORY_KINDS = {r: fam for r, (fam, key) in sl.APP_KINDS.items() if key == 'agentcore_memories'}
KINDS = dict(MEMORY_KINDS, **{r.replace('memories.', 'memorystrategies.'): fam for r, fam in MEMORY_KINDS.items()})
CALL_TIMEOUT = 60  # seconds, kubectl --request-timeout and subprocess timeout + 30
ABSENT = ("doesn't have a resource type", 'no matches for kind', 'could not find the requested resource')


def run_kubectl(args):
    """(rc, text): stdout on success, stderr on failure. A timeout is rc 124, never 'absent'."""
    try:
        p = subprocess.run([os.environ.get('KUBECTL', 'kubectl'), f'--request-timeout={CALL_TIMEOUT}s'] + args,
                           capture_output=True, text=True, timeout=CALL_TIMEOUT + 30)
    except subprocess.TimeoutExpired:
        return 124, 'timeout'
    return p.returncode, p.stdout if p.returncode == 0 else p.stderr


def effective_retained(family, item):
    """True when deleting the CR really leaves the memory in AWS. Unlike
    sweep_lib.already_retained, a managementPolicies that holds Delete (or '*') wins over
    deletionPolicy: Orphan, so such a CR is not retained."""
    spec = item.get('spec') or {}
    mp = spec.get('managementPolicies')
    if mp and ('Delete' in mp or '*' in mp):
        return False
    return (family == 'xp1' and spec.get('deletionPolicy') == 'Orphan') or bool(mp)


def composite_of(item):
    meta = item.get('metadata') or {}
    return (meta.get('labels') or {}).get('crossplane.io/composite') or next(
        (o.get('name') for o in meta.get('ownerReferences') or [] if o.get('controller')), '')


def patch_args(family, item):
    mp = (item.get('spec') or {}).get('managementPolicies')
    if family == 'xp1' and mp and ('Delete' in mp or '*' in mp):
        return ['patch', '--type', 'merge', '-p',
                json.dumps({'spec': {'deletionPolicy': 'Orphan', 'managementPolicies': sl.XP_NO_DELETE}})]
    return sl.retain_patch(family)


def list_items(kubectl, resource):
    """The CRs of one kind; [] when the CRD is not installed; None when the read failed."""
    for _ in range(2):
        rc, txt = kubectl(['get', resource, '-A', '-o', 'json'])
        if rc != 0 and any(a in (txt or '').lower() for a in ABSENT):
            return []
        if rc == 0:
            try:
                return json.loads(txt or '{}').get('items', [])
            except ValueError:
                pass
    return None


def main(argv, kubectl=None, out=sys.stdout):
    _, o = sl.parse_common(argv, __doc__)
    kubectl = kubectl or run_kubectl
    seen = failed = 0
    for resource, family in KINDS.items():
        items = list_items(kubectl, resource)
        if items is None:
            if kubectl(['get', '--raw', '/readyz'])[0] != 0:
                print(f'  WARNING hub unreachable ({resource} unreadable): nothing to keep, step 6c cannot act either',
                      file=out)
                return 1 if failed else 0
            failed += 1
            print(f'  ERROR could not read {resource} on a reachable hub: its memories cannot be checked', file=out)
            continue
        for it in items:
            meta = it.get('metadata') or {}
            name, ns = meta.get('name', ''), meta.get('namespace', '')
            where = f'{ns}/{name}' if ns else name
            mid = ((it.get('status') or {}).get('atProvider') or {}).get('id', '')
            seen += 1
            comp = composite_of(it)
            if comp:
                failed += 1
                print(f'  ERROR {resource} {where}: composed by {comp}; its Composition sets deletionPolicy: Delete '
                      f'and the composite reconciler reverts a patch, so this memory cannot be kept from here '
                      f'(fix: make the AgentCoreMemory Composition honour a retain setting, OAP)', file=out)
                continue
            if effective_retained(family, it):
                print(f'  keep {resource} {where}: already retained {mid}', file=out)
                continue
            print(f'  {"would retain" if o["dry_run"] else "retain"} {resource} {where} {mid}: '
                  f'DESTROY_KEEP_DATA=true', file=out)
            if o['dry_run']:
                continue
            args = patch_args(family, it)
            ref = [resource, name] + (['-n', ns] if ns else [])
            ok = kubectl([args[0]] + ref + args[1:])[0] == 0
            if ok:
                rc, txt = kubectl(['get'] + ref + ['-o', 'json'])
                try:
                    ok = rc == 0 and effective_retained(family, json.loads(txt or '{}'))
                except ValueError:
                    ok = False
            if not ok:
                failed += 1
                print(f'  ERROR could not retain {resource} {where}: its memory would be deleted', file=out)
    if not seen and not failed:
        print('  no AgentCore Memory CR on the hub: nothing to keep', file=out)
    elif failed:
        print(f'  ERROR {failed} AgentCore Memory CR(s)/read(s) not retained, of {seen} CR(s)', file=out)
    else:
        print(f'  {seen} AgentCore Memory CR(s) kept: deleting the CR leaves the memory in AWS. A reinstall with the '
              f'same app/memory name cannot create its memory while the kept one exists: adopt it '
              f'(crossplane.io/external-name) or delete it first', file=out)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
