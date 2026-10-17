"""RDS reaper (§4): DevLake's Aurora MySQL creates an ENI in the IDE VPC subnets.

Left behind, that ENI pins the private subnet (and then the VPC itself), so
CloudFormation's VPC delete fails with `DependencyViolation`. Observed twice in a
real pivot teardown: first the private subnet, then the VPC.

Root causes this reaper covers (it previously matched only
`DBInstanceIdentifier.startswith("devlake")` and deleted standalone instances):

  * DevLake is deployed WITH the resource prefix, so the real identifiers are
    `<prefix>-devlake-mysql-*` — `startswith("devlake")` never matched them, and
    the DB survived the whole sweep.
  * DevLake MySQL is an **Aurora cluster**: deleting the instance alone leaves the
    cluster (and its network) behind. Aurora requires member instances to be gone
    before the cluster can delete, so we delete instances, wait, then the cluster.
  * The `*-devlake-mysql-subnet-group` DB subnet group lingers (and name-collides
    on reused accounts — see issue #8). We delete it once the DBs are gone.
  * The delete must *drain* its ENI before the VPC reaper (§14) / CFN VPC delete
    runs, or the subnet stays pinned. We poll (best-effort, bounded) for drain.

Safety (review #1051): ownership is **prefix-anchored**, never a bare `"devlake"
in name` substring — the prefix exists so several deployments can share an
account, and a substring match would let one deployment's sweep delete another's
DevLake. We also NEVER clear `DeletionProtection` (the workshop never sets it, so
a protected DB is the strongest signal it isn't ours): a protected match is
skipped and logged, not force-deleted. CFN-managed resources
(`aws:cloudformation:*` tag) are always skipped.

The DevLake security group (`<prefix>-devlake-mysql-sg-*`) is cleared by the
IDE/hub VPC SG reaper (§15), which now succeeds precisely because the ENI has been
drained here first.
"""

from ..resilience import poll_until, run_delete


def _tags_of(resource):
    """RDS `describe_db_{instances,clusters}` return `TagList=[{Key,Value}]`.
    Normalise to a lower-cased key -> value dict (empty when absent)."""
    return {(t.get("Key") or "").lower(): (t.get("Value") or "")
            for t in (resource.get("TagList") or [])}


def _cfn_managed(tags):
    return any(k.startswith("aws:cloudformation:") for k in tags)


def _owned_devlake(name, tags, prefix):
    """Is this RDS instance/cluster THIS deployment's DevLake, and safe to delete?

    - `<prefix>-devlake-*` (the real #959 shape) is sufficient on its own.
    - A legacy bare `devlake-*` / `devlake` name is matched ONLY with a positive,
      *prefix-scoped* ownership signal — the ACK `eks:eks-capability-arn` tag,
      which names `<prefix>-hub`. Never matched on the substring alone, so one
      deployment's sweep cannot delete another deployment's DevLake.
    - A resource carrying any `aws:cloudformation:*` tag is Layer-1 CFN-managed and
      always skipped (consistent with finalnet/verify/delete_vpc_sgs).
    """
    n = (name or "").lower()
    p = (prefix or "").lower()
    if _cfn_managed(tags):
        return False
    if n.startswith(f"{p}-devlake-"):
        return True
    if n == "devlake" or n.startswith("devlake-"):
        # N1 (review #1051): compare the capability-name segment EXACTLY, not as a
        # substring. `f"{p}-hub" in arn` also matched another deployment's
        # .../capability/team-peeks-hub/... — the same cross-prefix class as #1.
        arn = tags.get("eks:eks-capability-arn", "").lower()
        return arn.split(":capability/", 1)[-1].split("/", 1)[0] == f"{p}-hub"
    return False


def _owned_devlake_subnet_group(sg, ctx):
    """Subnet-group ownership. `describe_db_subnet_groups` carries no TagList, so
    legacy bare names fall back to `vpc_is_ours(VpcId)` as the ownership signal."""
    n = (sg.get("DBSubnetGroupName") or "").lower()
    p = (ctx.prefix or "").lower()
    if n.startswith(f"{p}-devlake-"):
        return True
    if n == "devlake" or n.startswith("devlake-"):
        vio = getattr(ctx, "vpc_is_ours", None)
        return bool(vio and vio(sg.get("VpcId")))
    return False


def _devlake_instances(ctx):
    try:
        return [d for d in ctx.rds.describe_db_instances().get("DBInstances", [])
                if _owned_devlake(d.get("DBInstanceIdentifier"), _tags_of(d), ctx.prefix)]
    except Exception as e:
        ctx.log(f"RDS describe instances: {e}")
        return []


def _devlake_clusters(ctx):
    try:
        return [c for c in ctx.rds.describe_db_clusters().get("DBClusters", [])
                if _owned_devlake(c.get("DBClusterIdentifier"), _tags_of(c), ctx.prefix)]
    except Exception as e:
        ctx.log(f"RDS describe clusters: {e}")
        return []


def _devlake_subnet_groups(ctx):
    try:
        return [sg for sg in ctx.rds.describe_db_subnet_groups().get("DBSubnetGroups", [])
                if _owned_devlake_subnet_group(sg, ctx)]
    except Exception as e:
        ctx.log(f"RDS describe subnet groups: {e}")
        return []


def _deletable(resources, id_key):
    """Split owned resources into (deletable, protected). We never clear
    DeletionProtection: a protected match is left for an operator and reported."""
    deletable, protected = [], []
    for r in resources:
        (protected if r.get("DeletionProtection") else deletable).append(r[id_key])
    return deletable, protected


def _deleting_idents(resources, id_key, status_key):
    """Identifiers of owned, non-protected resources ALREADY in `deleting` state.

    ACK or `task destroy` may have issued the delete before §4 runs. Re-issuing it
    then returns InvalidDB{Instance,Cluster}StateFault, which classify() maps to
    'permanent' — so if §4 only trusts an accepted delete to gate its waits, an
    in-flight instance never gets waited on, the cluster delete fires while members
    are still deleting (InvalidDBClusterStateFault), and the subnet group leaks.
    Treat an already-`deleting` match as accepted: skip the delete, keep the wait
    (same rule §16c already applies at resweep.py). (review #1051)"""
    return {r[id_key] for r in resources
            if not r.get("DeletionProtection")
            and (r.get(status_key) or "").lower() == "deleting"}


def _no_devlake_eni(ctx):
    """True once no in-use RDS/DevLake ENI *belonging to this deployment* remains —
    i.e. the Aurora delete has drained its network interface so the subnet/VPC can be
    deleted. Scoped to THIS deployment (a prefix-anchored DevLake SG name, or an ENI
    in a VPC we own) so a co-tenant stack's DevLake/RDS ENI in the same region never
    makes us wait the full ceiling (review #1051). Never blocks teardown on a describe
    failure (returns True so the caller stops waiting)."""
    p = (ctx.prefix or "").lower()
    vpc_is_ours = getattr(ctx, "vpc_is_ours", None)
    try:
        enis = ctx.ec2.describe_network_interfaces(
            Filters=[{"Name": "interface-type", "Values": ["interface"]}]
        ).get("NetworkInterfaces", [])
        for eni in enis:
            desc = (eni.get("Description", "") or "").lower()
            group_names = [((g.get("GroupName") or "").lower()) for g in eni.get("Groups", [])]
            groups = " ".join(group_names)
            is_rds_eni = ("devlake" in groups or "devlake" in desc
                          or "rdsnetworkinterface" in desc.replace(" ", ""))
            if not is_rds_eni:
                continue
            # Scope to THIS deployment: a DevLake SG name ANCHORED on `<prefix>-devlake`
            # (per group name, not a substring of the joined list — else a co-tenant's
            # `team-<prefix>-devlake-mysql-sg-*` reads as ours), or an ENI in a VPC we
            # own. A co-tenant's `<other-prefix>-devlake-*` ENI (or any unrelated RDS
            # ENI) is ignored, so its presence can't make our teardown wait the full
            # ENI-drain ceiling (review #1051, N/ENI anchoring).
            ours = (any(g.startswith(f"{p}-devlake") for g in group_names)
                    or bool(vpc_is_ours and vpc_is_ours(eni.get("VpcId"))))
            if ours:
                return False
        return True
    except Exception:
        return True


def _c(code):
    return f" ({code})" if code else ""


def reap(ctx):
    """§4. Delete THIS deployment's DevLake Aurora stack (instances -> cluster ->
    subnet group) and wait for its ENI to drain, so the downstream VPC delete isn't
    blocked. Ownership is prefix-anchored; protected DBs are skipped, not cleared."""
    log, rds = ctx.log, ctx.rds

    instances = _devlake_instances(ctx)
    clusters = _devlake_clusters(ctx)
    subnet_groups = _devlake_subnet_groups(ctx)
    if not instances and not clusters and not subnet_groups:
        log("No DevLake RDS resources to delete")
        return

    del_instances, prot_instances = _deletable(instances, "DBInstanceIdentifier")
    del_clusters, prot_clusters = _deletable(clusters, "DBClusterIdentifier")
    for ident in prot_instances:
        log(f"  SKIP RDS instance {ident}: DeletionProtection=ON — not force-deleting (left as residue)")
    for ident in prot_clusters:
        log(f"  SKIP RDS cluster {ident}: DeletionProtection=ON — not force-deleting (left as residue)")

    # 1) Member / standalone instances first (Aurora: members must be gone before
    #    the cluster can delete). No modify_db_instance — we never clear protection.
    #    Track which deletes AWS accepted (deleted/gone): only those have anything to
    #    drain, so the waits below gate on these — not on what we merely attempted. A
    #    refused delete (access_denied/permanent) leaves nothing to wait for, so it
    #    must not burn the full poll ceiling (review #1051).
    deleted_instances = []
    deleting_instances = _deleting_idents(instances, "DBInstanceIdentifier", "DBInstanceStatus")
    for ident in del_instances:
        if ident in deleting_instances:
            # Already being deleted (ACK / task destroy got there first). Re-issuing
            # returns InvalidDBInstanceState='permanent'; instead treat it as accepted
            # so the drain below still waits for it to disappear (review #1051).
            log(f"  RDS instance {ident}: already deleting — not re-issued, waiting for drain")
            deleted_instances.append(ident)
            continue
        kind, code, _ = run_delete(lambda i=ident: rds.delete_db_instance(
            DBInstanceIdentifier=i, SkipFinalSnapshot=True, DeleteAutomatedBackups=True))
        log(f"  Deleting RDS instance {ident}: {kind}{_c(code)}")
        if kind in ("deleted", "gone"):
            deleted_instances.append(ident)

    # 2) Wait for the ACCEPTED instance deletes to drain so the cluster delete isn't
    #    ResourceInUse (~15 min ceiling; best-effort — §16 re-sweep is the backstop).
    if deleted_instances:
        drained = poll_until(
            lambda: not _deletable(_devlake_instances(ctx), "DBInstanceIdentifier")[0],
            attempts=45, delay=20.0)
        if not drained:
            log("DevLake RDS instances still present after wait — cluster delete may requeue")

    # 3) Aurora clusters, now that their members are gone.
    deleted_clusters = []
    deleting_clusters = _deleting_idents(clusters, "DBClusterIdentifier", "Status")
    for ident in del_clusters:
        if ident in deleting_clusters:
            log(f"  RDS cluster {ident}: already deleting — not re-issued, waiting for drain")
            deleted_clusters.append(ident)
            continue
        kind, code, _ = run_delete(lambda i=ident: rds.delete_db_cluster(
            DBClusterIdentifier=i, SkipFinalSnapshot=True))
        log(f"  Deleting RDS cluster {ident}: {kind}{_c(code)}")
        if kind in ("deleted", "gone"):
            deleted_clusters.append(ident)

    # 4) Wait for the Aurora ENI to drain before the VPC reaper / CFN VPC delete
    #    (~10 min ceiling). This is the step that prevents the DependencyViolation.
    #    Only wait if we actually got a DB delete accepted this run: a refused delete
    #    leaves no ENI to drain, and a subnet-group-only re-run (instances/clusters
    #    already gone) has nothing to wait for — otherwise every such run burns the
    #    full ceiling (review #1051).
    if deleted_instances or deleted_clusters:
        if poll_until(lambda: _no_devlake_eni(ctx), attempts=30, delay=20.0):
            log("DevLake RDS ENI drained")
        else:
            log("DevLake RDS ENI still present after wait — §14/§16 backstop will re-drive")

    # 5) DB subnet group (lingers; name-collides on reused accounts, issue #8).
    #    Delete ONLY after the owning clusters are actually gone, else RDS returns
    #    InvalidDBSubnetGroupStateFault (classified 'permanent', never retried) and
    #    the group leaks. Collected up front so a re-run with only the group left
    #    (instances/clusters already gone) still reaches this step (review #1051 §3).
    #    Gate the cluster-gone poll on clusters whose delete was ACCEPTED: a refused
    #    cluster delete will never go away, so waiting the full ceiling is pointless
    #    (the subnet delete just fails fast and is logged as residue).
    if subnet_groups:
        if deleted_clusters and not poll_until(lambda: not _devlake_clusters(ctx), attempts=30, delay=20.0):
            log("DevLake RDS clusters still present after wait — subnet group delete may requeue (§16 backstop)")
        for sg in subnet_groups:
            name = sg["DBSubnetGroupName"]
            kind, code, _ = run_delete(lambda n=name: rds.delete_db_subnet_group(DBSubnetGroupName=n))
            log(f"  Deleting RDS subnet group {name}: {kind}{_c(code)}")
            if kind not in ("deleted", "gone"):
                log(f"  RDS subnet group {name} not removed ({kind}{_c(code)}) — left as residue")
