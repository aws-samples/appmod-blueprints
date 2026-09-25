"""S3 reaper (§8c): imperatively-created buckets not in the CFN stack — the Ray
model cache (<prefix>-ray-models-<acct> / <hub>-ray-models-<acct>) and the
self-serve deploy-staging bucket. Prefix-scoped so shared bootstrap buckets
(cdk-hnb659fds-*, ws-assets-*) are never matched. Empties versions + markers first."""


def reap(ctx):
    log, s3, prefix, region = ctx.log, ctx.s3, ctx.prefix, ctx.region

    def _empty_bucket(bkt):
        paginator = s3.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bkt):
            batch = [
                {"Key": o["Key"], "VersionId": o["VersionId"]}
                for o in (page.get("Versions", []) + page.get("DeleteMarkers", []))
            ]
            for i in range(0, len(batch), 1000):
                try:
                    s3.delete_objects(Bucket=bkt, Delete={"Objects": batch[i:i + 1000], "Quiet": True})
                except Exception:
                    pass
        # Fallback for non-versioned buckets
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bkt):
            batch = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            for i in range(0, len(batch), 1000):
                try:
                    s3.delete_objects(Bucket=bkt, Delete={"Objects": batch[i:i + 1000], "Quiet": True})
                except Exception:
                    pass

    try:
        _reaped = 0
        for b in s3.list_buckets().get("Buckets", []):
            name = b["Name"]
            if not name.startswith(prefix + "-"):
                continue
            # Only touch buckets in this sweep's region (or us-east-1 global-style).
            try:
                loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
            except Exception:
                loc = region
            if loc != region:
                continue
            try:
                _empty_bucket(name)
                s3.delete_bucket(Bucket=name)
                _reaped += 1
                log(f"  Deleted S3 bucket {name}")
            except Exception as e:
                log(f"  S3 {name}: {e}")
        log(f"S3: deleted {_reaped} orphaned bucket(s)" if _reaped else "No orphaned S3 buckets to delete")
    except Exception as e:
        log(f"S3: {e}")
