#!/usr/bin/env python3
"""
sweep-ray-resources.py PREFIX AWS_REGION HUB ACCOUNT_ID [--keep-data]
                       [--dry-run [--assume-deleted HUB]]

task <provider>:destroy, after the hub cluster is deleted. Deletes what
cluster-providers/common/Taskfile.ray.yaml (ray:setup, ray:setup-neuron) creates with
the AWS CLI, which no CR owns and so nothing else deletes:
  * the S3 bucket PREFIX-ray-models-ACCOUNT_ID (the model cache), emptied first
    (every object version and delete marker); kept when it is in another region;
  * the ECR repositories PREFIX-ray-vllm-custom and PREFIX-ray-neuron-custom
    (deleted with their images).
Only these exact names, never a PREFIX-* pattern. Nothing while HUB is still a live
cluster (Ray still uses them). --keep-data (DESTROY_KEEP_DATA=true) keeps them all.
A read or delete error is logged with the AWS error code only and recorded in
destroy-sweep-failures for destroy's final check. Never fails destroy (exit 0).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, eks=None, s3=None, ecr=None, out=sys.stdout):
    pos, o = sl.parse_common(argv, __doc__)
    if len(pos) < 4 or not all(pos[:4]):
        print(__doc__, file=sys.stderr)
        return 2
    prefix, region, hub, account = pos[:4]
    try:
        eks = eks or sl.client('eks', region)
        live = sl.live_clusters(sl.cluster_inventory(eks), o['assume_deleted'])
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  ⚠ cannot read the EKS clusters ({sl.err_code(e)}): Ray resources not swept', file=out)
        sl.record_failure('sweep-ray-resources(eks)')
        return 0
    if hub in live:
        print(f'  skip Ray resources: hub {hub} is still {live[hub]["status"]} (Ray still uses them)', file=out)
        return 0
    try:
        s3 = s3 or sl.client('s3', region)
        ecr = ecr or sl.client('ecr', region)
        n, failed = sl.sweep_ray_resources(s3, ecr, prefix, account, region, o['keep_data'], o['dry_run'])
    except Exception as e:
        sl.reraise_credentials(e)
        print(f'  ⚠ Ray resource sweep stopped ({sl.err_code(e)})', file=out)
        sl.record_failure('sweep-ray-resources(stopped)')
        return 0
    for what in failed:
        sl.record_failure(f'sweep-ray-resources({what})')
    print(f'  Ray resources: {n} {"would be deleted" if o["dry_run"] else "deleted"}'
          f'{f", {len(failed)} not read or not deleted (recorded for the final check)" if failed else ""}',
          file=out)
    return 0


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-ray-resources'))
