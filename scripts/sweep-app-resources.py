#!/usr/bin/env python3
"""
sweep-app-resources.py PREFIX AWS_REGION HUB --inventory FILE
                       [--dry-run [--assume-deleted CLUSTER ...]]

task kind-kro-ack:destroy step 2c, after the hub cluster is deleted. Deletes the app
resources record-app-resources.py recorded from THIS hub's CRs
(destroy-app-resources.json next to the inventory, key HUB) that are still in AWS:
  * AgentCore memories (by recorded id): their Crossplane Memory CR was stranded
    when the crossplane-agentcore provider went first;
  * SQS queues and SNS topics (with their subscriptions) whose name starts with
    PREFIX-: stranded when the kro RGD, or the app's own ACK role selector, went
    before them (the aiops-agent <prefix>-amp-incidents topic, queue and DLQ).
Nothing is listed by pattern: only recorded ids. Nothing is deleted while HUB is
still a live cluster (its controllers own the resources then). --dry-run prints
"would delete" for each and deletes nothing; with --assume-deleted HUB it shows the
plan while the hub is still up. Never fails destroy (exit 0); a credential failure
is recorded for destroy's final check. Errors print the AWS error code only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, eks=None, client_for=None, out=sys.stdout):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 3 or not all(pos[:3]) or not o['inventory']:
        print(__doc__, file=sys.stderr)
        return 2
    prefix, region, hub = pos[:3]
    record = sl.load_app_record(sl.app_record_path(o['inventory']), hub)
    if not any(record[k] for k in sl.APP_KEYS):
        print(f'  no app resource recorded for {hub}: nothing to sweep', file=out)
        return 0
    try:
        eks = eks or sl.client('eks', region)
        live = sl.live_clusters(sl.cluster_inventory(eks), o['assume_deleted'])
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  ⚠ cannot read the EKS clusters ({sl.err_code(e)}): app resources not swept', file=out)
        sl.record_failure('sweep-app-resources(eks)')
        return 0
    if hub in live:
        print(f'  skip app resources: hub {hub} is still {live[hub]["status"]} (its controllers own them)',
              file=out)
        return 0
    selected, skipped = sl.select_app_resources(record, prefix)
    for what, why in skipped:
        print(f'  skip {what}: {why}', file=out)
    client_for = client_for or (lambda svc, r: sl.client(svc, r or region))
    try:
        n = sl.sweep_app_resources(selected, client_for, o['dry_run'])
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  ⚠ app resource sweep stopped ({sl.err_code(e)})', file=out)
        return 0
    total = sum(len(selected[k]) for k in sl.APP_KEYS)
    print(f'  app resources: {total} recorded in scope, {n} {"would be deleted" if o["dry_run"] else "deleted"}',
          file=out)
    return 0


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-app-resources'))
