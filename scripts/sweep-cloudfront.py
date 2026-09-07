#!/usr/bin/env python3
"""
sweep-cloudfront.py HUB_CLUSTER_NAME
Deletes CloudFront VPC origins and distributions associated with a peeks hub cluster.
Called by task kind-kro-ack:destroy step 6a.
"""
import boto3, sys, time

hub = sys.argv[1] if len(sys.argv) > 1 else 'peeks-hub'
cf = boto3.client('cloudfront')

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

# Disable then delete distributions
for dist_id in dist_ids:
    try:
        resp = cf.get_distribution_config(Id=dist_id)
        etag = resp['ETag']
        cfg = resp['DistributionConfig']
        if cfg.get('Enabled', True):
            cfg['Enabled'] = False
            cf.update_distribution(Id=dist_id, DistributionConfig=cfg, IfMatch=etag)
            print(f'  Disabling distribution {dist_id} (waiting for Deployed)...')
            for _ in range(20):
                if cf.get_distribution(Id=dist_id)['Distribution']['Status'] == 'Deployed':
                    break
                time.sleep(15)
        etag2 = cf.get_distribution(Id=dist_id)['ETag']
        cf.delete_distribution(Id=dist_id, IfMatch=etag2)
        print(f'  ✓ deleted distribution {dist_id}')
    except Exception as e:
        print(f'  distribution {dist_id}: {e}', file=sys.stderr)

time.sleep(5)
for vo_id in vo_ids:
    try:
        etag = cf.get_vpc_origin(Id=vo_id)['ETag']
        cf.delete_vpc_origin(Id=vo_id, IfMatch=etag)
        print(f'  ✓ deleted VPC origin {vo_id}')
    except Exception as e:
        print(f'  VPC origin {vo_id}: {e}', file=sys.stderr)
