"""S3 reaper (§8c): imperatively-created buckets not in the CFN stack — the Ray
model cache (<prefix>-ray-models-<acct> / <hub>-ray-models-<acct>) and the
self-serve deploy-staging bucket. Prefix-scoped so shared bootstrap buckets
(cdk-hnb659fds-*, ws-assets-*) are never matched. Empties versions + markers first.

CloudFormation-owned buckets (tag aws:cloudformation:stack-name) are NEVER reaped
here: CloudFormation deletes them itself, in its own order. The sweep runs in parallel
with the stack delete/rollback, and deleting the stack's bootstrap bucket under it made
the IDE bootstrap-script uploader fail with NoSuchBucket (stack ended ROLLBACK_FAILED,
N-21 cause A). If the tags cannot be read the bucket is left alone and counted as failed
(fail closed): a visible residue is better than a stack wedged in rollback."""

CFN_STACK_TAG = "aws:cloudformation:stack-name"


def _code(e):
    return getattr(e, "response", {}).get("Error", {}).get("Code", "")

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

    def _cfn_owner(bkt):
        """Stack name when the bucket belongs to a CloudFormation stack, "" when it has
        tags but no stack tag or no tag set at all. Raises on any other error."""
        try:
            tags = s3.get_bucket_tagging(Bucket=bkt).get("TagSet", [])
        except Exception as e:
            if _code(e) == "NoSuchTagSet":
                return ""
            raise
        return next((x.get("Value", "") for x in tags if x.get("Key") == CFN_STACK_TAG), "")

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
            try:
                owner = _cfn_owner(name)
            except Exception as e:
                if _code(e) == "NoSuchBucket":
                    continue  # already gone
                failed += 1
                considered += 1
                log(f"  S3 {name}: left alone, tags unreadable ({_code(e) or e}); not reaping a possibly stack-owned bucket")
                continue
            if owner:
                log(f"  S3 {name}: owned by CloudFormation stack {owner}, left to CloudFormation")
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
