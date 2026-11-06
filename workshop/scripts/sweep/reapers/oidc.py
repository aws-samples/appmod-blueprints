"""IAM OIDC providers of this deployment's EKS clusters (§7b).

Each EKS cluster gets an IAM OIDC provider (IRSA). The hub's is created by the hub's own
ACK capability and carries only eks:* tags, no platform.gitops.io/prefix tag, so neither
the IAM role reaper nor the §17d tag gate sees it, and it stayed behind whenever task
destroy did not reach its own OIDC step (6f). The spoke ones normally go with ACK.

A provider is ours only on positive identification, the same rules as task destroy 6f:
  * its URL is an EKS issuer of THIS region (oidc.eks.<region>.amazonaws.com/id/<id>);
  * an owner tag names one of our clusters exactly (hub + discovered spokes):
    eks:kubernetes-namespace or services.k8s.aws/namespace (the namespace of the ACK
    OpenIDConnectProvider = the cluster name), or eks:kubernetes-resource-name is
    "<cluster>-oidc", or eks:eks-capability-arn is a capability of our hub;
  * and its issuer id is not the issuer of any EKS cluster still present in the region.
Untagged or foreign providers are never deleted. If the region's clusters cannot be listed,
nothing is deleted (fail closed).
"""

from ..resilience import run_delete


def _active_issuer_ids(ctx):
    """Issuer ids of every EKS cluster present in the region, or None if unknown."""
    ids = set()
    try:
        for page in ctx.eks.get_paginator("list_clusters").paginate():
            for name in page.get("clusters", []):
                try:
                    issuer = ctx.eks.describe_cluster(name=name)["cluster"].get("identity", {}) \
                        .get("oidc", {}).get("issuer", "")
                except Exception as e:  # a cluster deleted between list and describe is fine
                    if "ResourceNotFound" in e.__class__.__name__ or "ResourceNotFound" in str(e):
                        continue
                    return None
                if issuer:
                    ids.add(issuer.rstrip("/").rsplit("/", 1)[-1])
    except Exception:
        return None
    return ids


def provider_is_ours(ctx, url, tags):
    if not url.startswith(f"oidc.eks.{ctx.region}.amazonaws.com/id/") and \
       not url.startswith(f"https://oidc.eks.{ctx.region}.amazonaws.com/id/"):
        return False
    clusters = ctx.owned_clusters()
    if tags.get("eks:kubernetes-namespace") in clusters:
        return True
    if tags.get("services.k8s.aws/namespace") in clusters:
        return True
    if tags.get("eks:kubernetes-resource-name") in {f"{c}-oidc" for c in clusters}:
        return True
    return f":capability/{ctx.hub}/" in tags.get("eks:eks-capability-arn", "")


def owned_providers(ctx):
    """ARNs of our OIDC providers whose cluster is gone, or None if it cannot be decided."""
    active = _active_issuer_ids(ctx)
    if active is None:
        return None
    out = []
    for p in ctx.iam.list_open_id_connect_providers().get("OpenIDConnectProviderList", []):
        arn = p["Arn"]
        d = ctx.iam.get_open_id_connect_provider(OpenIDConnectProviderArn=arn)
        url = d.get("Url", "")
        tags = {t["Key"]: t["Value"] for t in d.get("Tags", [])}
        if url.rstrip("/").rsplit("/", 1)[-1] in active:
            continue
        if provider_is_ours(ctx, url, tags):
            out.append(arn)
    return out


def reap(ctx):
    log = ctx.log
    try:
        arns = owned_providers(ctx)
    except Exception as e:
        log(f"OIDC providers: cannot list ({e.__class__.__name__}); none deleted")
        return
    if arns is None:
        log("OIDC providers: EKS clusters of the region cannot be listed; none deleted")
        return
    if not arns:
        log("No orphaned OIDC providers to delete")
        return
    deleted = denied = failed = 0
    for arn in arns:
        kind, code, _msg = run_delete(
            lambda arn=arn: ctx.iam.delete_open_id_connect_provider(OpenIDConnectProviderArn=arn))
        oid = arn.rsplit("/", 1)[-1]
        if kind == "deleted":
            deleted += 1
            log(f"  Deleted OIDC provider {oid}")
        elif kind == "gone":
            pass
        elif kind == "access_denied":
            denied += 1
            log(f"  ACCESS DENIED deleting OIDC provider {oid} ({code})")
        else:
            failed += 1
            log(f"  OIDC provider {oid} not deleted ({kind}: {code})")
    log(f"OIDC providers: deleted {deleted}; {denied} access-denied, {failed} failed")
