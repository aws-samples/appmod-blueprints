"""ECR reaper (§8b): the imperatively-created Ray/vLLM inference repo
(<prefix>-ray-vllm-custom) has no owning CR, so task destroy leaves it behind."""


def reap(ctx):
    log, ecr, prefix = ctx.log, ctx.ecr, ctx.prefix
    try:
        _reaped = 0
        for _name in [f"{prefix}-ray-vllm-custom"]:
            try:
                ecr.delete_repository(repositoryName=_name, force=True)
                _reaped += 1
                log(f"  Deleted ECR repository {_name}")
            except ecr.exceptions.RepositoryNotFoundException:
                pass
            except Exception as e:
                log(f"  ECR {_name}: {e}")
        log(f"ECR: force-deleted {_reaped} orphaned repository(ies)")
    except Exception as e:
        log(f"ECR: {e}")
