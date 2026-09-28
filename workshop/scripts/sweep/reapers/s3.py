"""S3 reaper (§8c): imperatively-created buckets not in the CFN stack — the Ray
model cache (<prefix>-ray-models-<acct> / <hub>-ray-models-<acct>) and the
self-serve deploy-staging bucket. Prefix-scoped so shared bootstrap buckets
(cdk-hnb659fds-*, ws-assets-*) are never matched. Empties versions + markers first."""

from ..resilience import run_delete


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
        considered = deleted = gone = access_denied = failed = 0
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
            considered += 1
            _empty_bucket(name)
            # run_delete: transient-retry + honest classification (no bare except,
            # 'gone' not conflated with a real delete, access-denied surfaced #932).
            kind, code, msg = run_delete(lambda n=name: s3.delete_bucket(Bucket=n))
            if kind == "deleted":
                deleted += 1
                log(f"  Deleted S3 bucket {name}")
            elif kind == "gone":
                gone += 1  # already absent — not counted as a delete we performed
            elif kind == "access_denied":
                access_denied += 1
                log(f"  S3 {name}: ACCESS DENIED ({code})")
            else:  # transient (retries exhausted, e.g. BucketNotEmpty) | permanent
                failed += 1
                log(f"  S3 {name}: failed ({kind}) {code}: {msg}")
        # Marker gated on "no bucket considered", NOT on "0 deleted": a run where every
        # matched bucket hit AccessDenied must NOT report "nothing to delete" (#932).
        if considered == 0:
            log("No orphaned S3 buckets to delete")
        else:
            log(
                f"S3: deleted {deleted} orphaned bucket(s)"
                f"; {access_denied} access-denied, {failed} failed"
            )
    except Exception as e:
        log(f"S3: {e}")
