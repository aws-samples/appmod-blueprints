"""ECR reaper (§8b): the imperatively-created Ray/vLLM inference repo
(<prefix>-ray-vllm-custom) has no owning CR, so task destroy leaves it behind."""

from ..resilience import run_delete


def reap(ctx):
    log, ecr, prefix = ctx.log, ctx.ecr, ctx.prefix
    try:
        deleted = gone = access_denied = failed = 0
        for name in [f"{prefix}-ray-vllm-custom"]:
            # run_delete: transient-retry + honest classification (no bare except,
            # 'gone' not conflated with a real delete, access-denied surfaced #932).
            kind, code, msg = run_delete(
                lambda n=name: ecr.delete_repository(repositoryName=n, force=True)
            )
            if kind == "deleted":
                deleted += 1
                log(f"  Deleted ECR repository {name}")
            elif kind == "gone":
                gone += 1  # already absent — not counted as a delete we performed
            elif kind == "access_denied":
                access_denied += 1
                log(f"  ECR {name}: ACCESS DENIED ({code})")
            else:  # transient (retries exhausted) | permanent
                failed += 1
                log(f"  ECR {name}: failed ({kind}) {code}: {msg}")
        # Keep the "force-deleted N" summary (consumed by the orchestration test) and
        # append honest access-denied/failed counts so a hidden failure can't pass as
        # a clean run (#932).
        log(
            f"ECR: force-deleted {deleted} orphaned repository(ies)"
            f"; {access_denied} access-denied, {failed} failed"
        )
    except Exception as e:
        log(f"ECR: {e}")
