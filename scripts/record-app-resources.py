#!/usr/bin/env python3
"""
record-app-resources.py AWS_REGION HUB --inventory FILE [--dry-run]

Run by task kind-kro-ack:destroy while the hub is still readable (inventory step),
on the hub kubeconfig ($KUBECONFIG). Records the AWS ids of the app resources the
hub's controllers own through CRs that a teardown can strand:
  * Crossplane bedrockagentcore Memory (v1 cluster-scoped, v2 namespaced): the
    memory id (status.atProvider.id, else crossplane.io/external-name);
  * ACK SNS Topic and SQS Queue: the ARN (status.ackResourceMetadata.arn).
A CR that keeps its AWS object (ACK deletion-policy=retain, Crossplane Orphan or no
Delete in managementPolicies) is not recorded, and neither is a CR with no AWS id
yet. The record (destroy-app-resources.json next to the inventory, keyed by HUB) is
merged, never truncated, so a re-run after the hub is gone keeps what an earlier
run saw. sweep-app-resources.py deletes these once the hub is gone.

Read-only on the cluster and on AWS. --dry-run prints and writes nothing.
Exits 0 when the hub is unreachable (nothing to record then).
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


def list_app_crs(kubectl):
    out = {}
    for resource in sl.APP_KINDS:
        rc, txt = kubectl(['get', resource, '-A', '-o', 'json'])
        if rc != 0:
            continue  # CRD not installed on this hub, or hub unreachable
        try:
            items = json.loads(txt or '{}').get('items', [])
        except ValueError:
            continue
        if items:
            out[resource] = items
    return out


def main(argv, kubectl=None, out=sys.stdout):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 2 or not all(pos[:2]) or not o['inventory']:
        print(__doc__, file=sys.stderr)
        return 2
    region, hub = pos[:2]
    found = sl.collect_app_resources(list_app_crs(kubectl or run_kubectl), region)
    path = sl.app_record_path(o['inventory'])
    try:
        with open(path) as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        data = {}
    merged = sl.merge_app_record(data.get(hub), found)
    for k in sl.APP_KEYS:
        for r in found[k]:
            print(f'  record {k[:-1].replace("_", " ")} {r.get("id") or r.get("name")}', file=out)
    total = sum(len(merged[k]) for k in sl.APP_KEYS)
    if o['dry_run']:
        print(f'  [dry-run] would record {total} app resource(s) of {hub} in {path}', file=out)
        return 0
    data[hub] = merged
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=1, sort_keys=True)
    except OSError as e:
        print(f'  WARN could not write {path} ({e})', file=out)
        return 0
    print(f'  recorded {total} app resource(s) of {hub} (AgentCore memories, SNS topics, SQS queues)',
          file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
