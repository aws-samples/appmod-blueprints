#!/usr/bin/env python3
"""
drain-oam-apps.py HUB WAIT_SECONDS [--dry-run]

task kind-kro-ack:hub:destroy-addons step 6c, on the hub kubeconfig ($KUBECONFIG),
after the spokes and BEFORE the per-addon pass (step 7).

An app the hub deploys as a KubeVela (OAM) Application, such as the OAP aiops-agent,
owns AWS resources through CRs that other addons' controllers delete: a Crossplane
bedrockagentcore Memory (provider: the crossplane-agentcore addon), a kro AmpIncident
whose ACK SNS topic and SQS queues need the kro RGD (kro-amp-incident-rgd-hub), and
KubeVela itself to garbage-collect all of them. Step 7 removes addons one after the
other with 120 s per addon, so these controllers went while the app was still being
deleted, and its memory, topic and queues stayed in AWS once the hub was gone.

This step removes those apps first, while every controller is alive:
  1. find the Argo CD Applications that manage a core.oam.dev Application on the hub
     (destination name HUB or in-cluster);
  2. delete their ApplicationSets (preserveResourcesOnDeletion=false), as step 7
     would, or the Application itself when no ApplicationSet owns it;
  3. wait, bounded by WAIT_SECONDS (polled every 15 s), while any of: those Argo CD
     Applications, a core.oam.dev Application in their namespaces, a Crossplane
     managed resource or a kro instance applied by KubeVela (label app.oam.dev/name)
     that is being deleted. It stops waiting at once when no KubeVela controller is
     running (nothing can make progress then).
Best-effort, never fails the teardown (exit 0). Nothing else is deleted. --dry-run
prints the plan and deletes nothing. The AWS sweep (sweep-app-resources.py) still
backstops whatever this wait could not finish.
"""
import json
import os
import subprocess
import sys
import time

POLL = 15
VELA_NS = 'vela-system'
APP_LABEL = 'app.oam.dev/name'


def run_kubectl(args):
    p = subprocess.run([os.environ.get('KUBECTL', 'kubectl')] + args,
                       capture_output=True, text=True)
    return p.returncode, p.stdout


def _json(kubectl, args):
    rc, txt = kubectl(args + ['-o', 'json'])
    if rc != 0:
        return None
    try:
        return json.loads(txt or '{}')
    except ValueError:
        return None


def _targets_hub(app, hub):
    d = (app.get('spec') or {}).get('destination') or {}
    return d.get('name') in (hub, 'in-cluster') or d.get('server') == 'https://kubernetes.default.svc'


def oam_argo_apps(apps_json, hub):
    """[(app name, owner ApplicationSet or '', {OAM namespaces})] of the Argo CD
    Applications that manage a core.oam.dev Application on the hub."""
    out = []
    for a in (apps_json or {}).get('items', []):
        res = [r for r in (a.get('status') or {}).get('resources') or []
               if r.get('group') == 'core.oam.dev' and r.get('kind') == 'Application']
        if not res or not _targets_hub(a, hub):
            continue
        meta = a.get('metadata') or {}
        owner = next((o.get('name', '') for o in meta.get('ownerReferences') or []
                      if o.get('kind') == 'ApplicationSet'), '')
        out.append((meta.get('name', ''), owner, {r.get('namespace', '') for r in res if r.get('namespace')}))
    return out


def _deleting_by_vela(items):
    return sorted(f'{(i.get("kind") or "").lower()}/{(i.get("metadata") or {}).get("name", "")}'
                  for i in items
                  if (i.get('metadata') or {}).get('deletionTimestamp')
                  and APP_LABEL in ((i.get('metadata') or {}).get('labels') or {}))


def pending(kubectl, names, namespaces):
    """What the drain still waits for, as short strings (empty: done)."""
    left = []
    apps = _json(kubectl, ['get', 'applications.argoproj.io', '-n', 'argocd'])
    if apps is not None:
        have = {(i.get('metadata') or {}).get('name') for i in apps.get('items', [])}
        left += [f'argocd/{n}' for n in names if n in have]
    for ns in sorted(namespaces):
        oam = _json(kubectl, ['get', 'applications.core.oam.dev', '-n', ns])
        if oam is not None:
            left += [f'oam/{ns}/{(i.get("metadata") or {}).get("name", "")}' for i in oam.get('items', [])]
    mr = _json(kubectl, ['get', 'managed'])
    if mr is not None:
        left += _deleting_by_vela(mr.get('items', []))
    rgds = _json(kubectl, ['get', 'resourcegraphdefinitions.kro.run'])
    kinds = sorted({((r.get('spec') or {}).get('schema') or {}).get('kind', '')
                    for r in (rgds or {}).get('items', [])} - {''})
    for k in kinds:
        inst = _json(kubectl, ['get', f'{k.lower()}.kro.run', '-A'])
        if inst is not None:
            left += _deleting_by_vela(inst.get('items', []))
    return left


def vela_running(kubectl):
    pods = _json(kubectl, ['get', 'pods', '-n', VELA_NS])
    return any((p.get('status') or {}).get('phase') == 'Running'
               and 'vela-core' in (p.get('metadata') or {}).get('name', '')
               for p in (pods or {}).get('items', []))


def main(argv, kubectl=None, sleep=None, out=sys.stdout):
    dry = '--dry-run' in argv
    pos = [a for a in argv if not a.startswith('--')]
    if len(pos) < 2 or not pos[0]:
        print(__doc__, file=sys.stderr)
        return 2
    hub = pos[0]
    try:
        wait = max(0, int(pos[1]))
    except ValueError:
        wait = 1200
    kubectl = kubectl or run_kubectl
    sleep = sleep or time.sleep
    apps = _json(kubectl, ['get', 'applications.argoproj.io', '-n', 'argocd'])
    if apps is None:
        print('  6c: could not query Argo CD Applications (hub unreachable?): nothing to drain', file=out)
        return 0
    found = oam_argo_apps(apps, hub)
    if not found:
        print('  6c: no OAM (KubeVela) app on the hub: nothing to drain', file=out)
        return 0
    names = [n for n, _, _ in found]
    owners = sorted({o for _, o, _ in found if o})
    orphans = sorted(n for n, o, _ in found if not o)
    namespaces = set().union(*[ns for _, _, ns in found])
    verb = 'would delete' if dry else 'deleting'
    for o in owners:
        print(f'  6c: {verb} ApplicationSet {o} (manages an OAM app on {hub}) before its controllers', file=out)
        if not dry:
            kubectl(['patch', 'applicationset', o, '-n', 'argocd', '--type', 'merge', '-p',
                     json.dumps({'spec': {'syncPolicy': {'preserveResourcesOnDeletion': False}}})])
            kubectl(['delete', 'applicationset', o, '-n', 'argocd', '--timeout=180s'])
    for n in orphans:
        print(f'  6c: {verb} Application {n} (manages an OAM app on {hub}, no ApplicationSet)', file=out)
        if not dry:
            kubectl(['delete', 'application', n, '-n', 'argocd', '--wait=false'])
    if dry:
        print(f'  6c: [dry-run] would then wait up to {wait}s for: {", ".join(names)} '
              f'and their OAM resources in {", ".join(sorted(namespaces)) or "-"}', file=out)
        return 0
    waited = 0
    while True:
        left = pending(kubectl, names, namespaces)
        if not left:
            print(f'  6c: OAM apps drained ({waited}s)', file=out)
            return 0
        if waited >= wait:
            print(f'  6c: still deleting after {waited}s, going on (the AWS sweep backstops): '
                  f'{" ".join(left)}', file=out)
            return 0
        if not vela_running(kubectl):
            print(f'  6c: no KubeVela controller running: not waiting for {" ".join(left)}', file=out)
            return 0
        print(f'  6c: waiting for the OAM apps to delete their resources: {" ".join(left)} ({waited}s)',
              file=out)
        sleep(POLL)
        waited += POLL


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
