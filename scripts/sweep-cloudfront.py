#!/usr/bin/env python3
"""
sweep-cloudfront.py HUB_CLUSTER_NAME
Deletes CloudFront VPC origins and distributions associated with a peeks hub cluster.
Called by task kind-kro-ack:destroy step 6a.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402

# The disable -> wait for Deployed -> delete sequence is shared with the workshop
# reaper (#1299, #1301) so the two teardown paths cannot drift apart again.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'workshop', 'scripts'))
from sweep.reapers.cloudfront import disable_and_delete  # noqa: E402

hub = sys.argv[1] if len(sys.argv) > 1 else 'peeks-hub'
try:
    # Same profile as the aws CLI calls of the task, credentials checked up front:
    # without them the listing below "found nothing" and the sweep reported success.
    cf = sl.client('cloudfront')
except sl.CredentialsError as e:
    print(f'ERROR sweep-cloudfront: {e}. Nothing was swept.', file=sys.stderr)
    sl.record_failure('sweep-cloudfront')
    sys.exit(sl.CREDENTIALS_EXIT)

# Find VPC origins for this hub (named <hub>-*)
vo_ids = set()
try:
    items = cf.list_vpc_origins().get('VpcOriginList', {}).get('Items', [])
    for item in items:
        if item['Name'].startswith(hub + '-'):
            vo_ids.add(item['Id'])
            print(f'  Found VPC origin: {item["Id"]} ({item["Name"]})')
except Exception as e:
    print(f'  list-vpc-origins error: {e}', file=sys.stderr)

# Find distributions that reference our VPC origins or match hub name in Comment
dist_ids = set()
try:
    dists = cf.list_distributions().get('DistributionList', {}).get('Items', [])
    for d in dists:
        comment = d.get('Comment', '')
        if comment.startswith(hub):
            dist_ids.add(d['Id'])
            print(f'  Found distribution by comment: {d["Id"]} ({comment})')
            continue
        for o in d.get('Origins', {}).get('Items', []):
            if o.get('VpcOriginConfig', {}).get('VpcOriginId', '') in vo_ids:
                dist_ids.add(d['Id'])
                print(f'  Found distribution by VPC origin: {d["Id"]}')
                break
except Exception as e:
    print(f'  list-distributions error: {e}', file=sys.stderr)

if not vo_ids and not dist_ids:
    print('  No CloudFront resources to clean up.')
    sys.exit(0)

# Disable then delete distributions: waits up to ~20 min for Deployed, also when the
# distribution was already Enabled=False but still InProgress, and retries a
# DistributionNotDisabled refusal. Never raises.
for dist_id in dist_ids:
    disable_and_delete(cf, dist_id, print)

time.sleep(5)
for vo_id in vo_ids:
    try:
        etag = cf.get_vpc_origin(Id=vo_id)['ETag']
        cf.delete_vpc_origin(Id=vo_id, IfMatch=etag)
        print(f'  ✓ deleted VPC origin {vo_id}')
    except Exception as e:
        print(f'  VPC origin {vo_id}: {e}', file=sys.stderr)
