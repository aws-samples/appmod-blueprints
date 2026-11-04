"""App-layer residue net (§16c): prefix-scoped safety net for what `task destroy` leaves
when it did not run (or did not finish) before the clusters are deleted cold.

`task destroy` is what drains the PVCs and lets ArgoCD/kro/ACK/Crossplane remove their
cloud resources. When it is skipped, the sweep deleted the clusters but these families
stayed behind and §17 did not see them (R-27):

  * EBS volumes left `available` by the EBS CSI driver (PVCs whose cluster is gone),
  * ECR repositories `<prefix>/*` (Rust/Java CI/CD repos and their `/cache` repos),
  * DynamoDB tables `<prefix>-*`,
  * SSM parameters `/<prefix>/*`,
  * fluent-bit log groups `/aws/eks/fluentbit-cloudwatch/<prefix>-*`.

SAFETY: every family is matched by the prefix (or by the cluster tag whose cluster name
starts with `<prefix>-`) and nothing else; a resource without it is never touched. EBS
volumes are deleted only when `available` (not attached) and only when their cluster tag
does not name a LIVE EKS cluster that is not ours. A DynamoDB table with deletion
protection is left in place and reported by §17 (the sweep never switches protection off).

`enumerate_families(ctx)` is shared with the §17 gate: the reaper deletes what it lists,
the gate lists the same families and re-checks that each resource still exists.

SWEEP_DRY_RUN=1 lists what would be deleted and deletes nothing.
"""

import os

from ..resilience import classify, run_delete

EBS_CLUSTER_KEY_PREFIX = "kubernetes.io/cluster/"
EBS_CSI_CLUSTER_KEY = "ebs.csi.eks.amazonaws.com/cluster"
FLUENTBIT_LOG_ROOT = "/aws/eks/fluentbit-cloudwatch/"

FAMILIES = ("ebs", "ecr", "dynamodb", "ssm", "log-group")


def is_dry_run(ctx):
    return bool(getattr(ctx, "dry_run", False)) or os.environ.get(
        "SWEEP_DRY_RUN", "").lower() in ("1", "true", "yes")


def _owned_name(name, prefix):
    """<prefix>-* only. A bare `startswith(prefix)` would take every stack whose prefix
    merely starts with ours ("tdv" vs "tdv2-hub", #1111)."""
    return bool(name) and name.startswith(prefix + "-")


def _tags(resource):
    return {t.get("Key"): t.get("Value") for t in resource.get("Tags", [])}


# ── EBS ────────────────────────────────────────────────────────────────────────

def _volume_cluster(tags, prefix):
    """The owning cluster name of an EBS CSI volume if it is ours, else None."""
    for key, value in tags.items():
        if key and key.startswith(EBS_CLUSTER_KEY_PREFIX):
            cluster = key[len(EBS_CLUSTER_KEY_PREFIX):]
            if _owned_name(cluster, prefix):
                return cluster
    if _owned_name(tags.get(EBS_CSI_CLUSTER_KEY, ""), prefix):
        return tags[EBS_CSI_CLUSTER_KEY]
    return None


def _live_foreign_clusters(ctx):
    """Names of live EKS clusters that are NOT ours. None when they cannot be listed
    (callers then leave every volume alone: fail closed)."""
    try:
        live = set()
        for page in ctx.eks.get_paginator("list_clusters").paginate():
            live.update(page.get("clusters", []))
        return live - set(ctx.owned_clusters())
    except Exception as e:
        ctx.log(f"  [residue] EKS cluster list for the EBS check: {e}")
        return None


def list_ebs(ctx):
    """[(volume_id, cluster)] for available volumes tagged for one of our clusters.
    Raises on a describe error so the caller can report it."""
    prefix = ctx.prefix
    found = {}
    filters = (
        [{"Name": "tag-key", "Values": [f"{EBS_CLUSTER_KEY_PREFIX}{prefix}-*"]}],
        [{"Name": f"tag:{EBS_CSI_CLUSTER_KEY}", "Values": [f"{prefix}-*"]}],
    )
    for extra in filters:
        flt = [{"Name": "status", "Values": ["available"]}] + extra
        for page in ctx.ec2.get_paginator("describe_volumes").paginate(Filters=flt):
            for v in page.get("Volumes", []):
                if v.get("State", "available") != "available" or v.get("Attachments"):
                    continue
                cluster = _volume_cluster(_tags(v), prefix)
                if cluster:  # re-checked in Python: the API wildcard is only a pre-filter
                    found[v["VolumeId"]] = cluster
    return sorted(found.items())


# ── per-family listers (each returns the resource ids/names) ────────────────────

def list_ecr(ctx):
    out = []
    for page in ctx.ecr.get_paginator("describe_repositories").paginate():
        for r in page.get("repositories", []):
            if r["repositoryName"].startswith(ctx.prefix + "/"):
                out.append(r["repositoryName"])
    return sorted(out)


def list_dynamodb(ctx):
    out = []
    for page in ctx.ddb.get_paginator("list_tables").paginate():
        out.extend(n for n in page.get("TableNames", []) if _owned_name(n, ctx.prefix))
    return sorted(out)


def list_ssm(ctx):
    root = f"/{ctx.prefix}/"
    out = []
    for page in ctx.ssm.get_paginator("describe_parameters").paginate(
        ParameterFilters=[{"Key": "Name", "Option": "BeginsWith", "Values": [root]}]
    ):
        out.extend(p["Name"] for p in page.get("Parameters", []) if p["Name"].startswith(root))
    return sorted(out)


def list_log_groups(ctx):
    root = f"{FLUENTBIT_LOG_ROOT}{ctx.prefix}-"
    out = []
    for page in ctx.logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=root):
        out.extend(g["logGroupName"] for g in page.get("logGroups", [])
                   if g["logGroupName"].startswith(root))
    return sorted(out)


def enumerate_families(ctx):
    """{family: [token, ...]} of what is currently listed. A family whose listing fails is
    reported under errors, never treated as empty-and-clean by the reaper log."""
    listers = (
        ("ebs", lambda: [v for v, _c in list_ebs(ctx)]),
        ("ecr", lambda: list_ecr(ctx)),
        ("dynamodb", lambda: list_dynamodb(ctx)),
        ("ssm", lambda: list_ssm(ctx)),
        ("log-group", lambda: list_log_groups(ctx)),
    )
    found, errors = {}, {}
    for fam, fn in listers:
        try:
            found[fam] = fn()
        except Exception as e:  # noqa: BLE001 — surfaced, classified
            found[fam] = []
            errors[fam] = f"{classify(e)} {e.__class__.__name__}"
    return found, errors


# ── existence re-check (used by the §17 gate) ───────────────────────────────────

def still_exists(ctx, family, ident):
    """True when the resource is still there. A lookup that cannot decide (throttled,
    denied) answers True: the gate must not hide a resource it could not check."""
    try:
        if family == "ebs":
            vols = ctx.ec2.describe_volumes(VolumeIds=[ident]).get("Volumes", [])
            return bool(vols)
        if family == "ecr":
            return bool(ctx.ecr.describe_repositories(repositoryNames=[ident]).get("repositories", []))
        if family == "dynamodb":
            ctx.ddb.describe_table(TableName=ident)
            return True
        if family == "ssm":
            return bool(ctx.ssm.get_parameter(Name=ident).get("Parameter"))
        if family == "log-group":
            return any(g["logGroupName"] == ident for g in
                       ctx.logs.describe_log_groups(logGroupNamePrefix=ident).get("logGroups", []))
    except Exception as e:  # noqa: BLE001
        return classify(e) != "gone"
    return True


# ── reaper ──────────────────────────────────────────────────────────────────────

def _delete_all(ctx, family, idents, delete_fn, label):
    """Delete each ident via run_delete; returns (deleted, gone, access_denied, failed)."""
    deleted = gone = denied = failed = 0
    for ident in idents:
        if is_dry_run(ctx):
            ctx.log(f"  [dry-run] would delete {label} {ident}")
            continue
        kind, code, msg = run_delete(lambda i=ident: delete_fn(i))
        if kind == "deleted":
            deleted += 1
            ctx.log(f"  Deleted {label} {ident}")
        elif kind == "gone":
            gone += 1
        elif kind == "access_denied":
            denied += 1
            ctx.log(f"  {label} {ident}: ACCESS DENIED ({code})")
        else:
            failed += 1
            ctx.log(f"  {label} {ident}: failed ({kind}) {code}: {msg}")
    return deleted, gone, denied, failed


def _summary(ctx, family, listed, counts):
    deleted, gone, denied, failed = counts
    if is_dry_run(ctx):
        ctx.log(f"Residue/{family}: dry-run, {listed} would be deleted")
    else:
        ctx.log(f"Residue/{family}: deleted {deleted}/{listed}; "
                f"{gone} already gone, {denied} access-denied, {failed} failed")


def _protected_tables(ctx, names):
    """Tables with deletion protection: left alone (the sweep never turns protection off)."""
    keep = []
    for n in names:
        try:
            if ctx.ddb.describe_table(TableName=n)["Table"].get("DeletionProtectionEnabled"):
                ctx.log(f"  DynamoDB {n}: deletion protection is on, leaving it (reported by §17)")
                continue
        except Exception:  # noqa: BLE001 — gone or unreadable: let the delete decide
            pass
        keep.append(n)
    return keep


def reap(ctx):
    """§16c."""
    log = ctx.log
    found, errors = enumerate_families(ctx)
    for fam, err in errors.items():
        log(f"Residue/{fam}: listing failed ({err}) — nothing deleted for this family")

    # EBS: only volumes whose cluster is not a live foreign cluster.
    vols = []
    if "ebs" not in errors:
        foreign = _live_foreign_clusters(ctx)
        if foreign is None:
            log("Residue/ebs: cannot confirm no foreign live cluster owns a volume — leaving them")
        else:
            by_cluster = dict(list_ebs(ctx))
            vols = [v for v in found["ebs"] if by_cluster.get(v) not in foreign]
            skipped = len(found["ebs"]) - len(vols)
            if skipped:
                log(f"Residue/ebs: {skipped} volume(s) belong to a live cluster that is not ours — left alone")
    _summary(ctx, "ebs", len(vols),
             _delete_all(ctx, "ebs", vols, lambda i: ctx.ec2.delete_volume(VolumeId=i), "EBS volume"))

    _summary(ctx, "ecr", len(found["ecr"]),
             _delete_all(ctx, "ecr", found["ecr"],
                         lambda i: ctx.ecr.delete_repository(repositoryName=i, force=True), "ECR repository"))

    tables = _protected_tables(ctx, found["dynamodb"])
    _summary(ctx, "dynamodb", len(tables),
             _delete_all(ctx, "dynamodb", tables, lambda i: ctx.ddb.delete_table(TableName=i), "DynamoDB table"))

    _summary(ctx, "ssm", len(found["ssm"]),
             _delete_all(ctx, "ssm", found["ssm"], lambda i: ctx.ssm.delete_parameter(Name=i), "SSM parameter"))

    _summary(ctx, "log-group", len(found["log-group"]),
             _delete_all(ctx, "log-group", found["log-group"],
                         lambda i: ctx.logs.delete_log_group(logGroupName=i), "log group"))
