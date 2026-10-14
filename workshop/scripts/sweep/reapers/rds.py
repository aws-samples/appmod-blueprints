"""RDS reaper (§4): DevLake's Aurora MySQL creates an ENI in the IDE VPC subnets.

Left behind, that ENI pins the private subnet (and then the VPC itself), so
CloudFormation's VPC delete fails with `DependencyViolation`. Observed twice in a
real pivot teardown: first the private subnet, then the VPC.

Root causes this reaper now covers (it previously matched only
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

The DevLake security group (`<prefix>-devlake-mysql-sg-*`) is cleared by the
IDE/hub VPC SG reaper (§15), which now succeeds precisely because the ENI has been
drained here first.
"""

from ..resilience import poll_until, run_delete


def _is_devlake(identifier, prefix):
    """DevLake DB/cluster/subnet-group names: `<prefix>-devlake-*` (prefixed, the
    real shape) OR a bare `devlake*` (legacy / fixed `${metadata.name}` names)."""
    i = (identifier or "").lower()
    return "devlake" in i or i.startswith(f"{prefix}-devlake")


def _devlake_instances(ctx):
    try:
        return [d["DBInstanceIdentifier"]
                for d in ctx.rds.describe_db_instances().get("DBInstances", [])
                if _is_devlake(d["DBInstanceIdentifier"], ctx.prefix)]
    except Exception as e:
        ctx.log(f"RDS describe instances: {e}")
        return []


def _devlake_clusters(ctx):
    try:
        return [c["DBClusterIdentifier"]
                for c in ctx.rds.describe_db_clusters().get("DBClusters", [])
                if _is_devlake(c["DBClusterIdentifier"], ctx.prefix)]
    except Exception as e:
        ctx.log(f"RDS describe clusters: {e}")
        return []


def _no_devlake_eni(ctx):
    """True once no in-use RDS/DevLake ENI remains — i.e. the Aurora delete has
    drained its network interface so the subnet/VPC can be deleted. Never blocks
    teardown on a describe failure (returns True so the caller stops waiting)."""
    try:
        enis = ctx.ec2.describe_network_interfaces(
            Filters=[{"Name": "interface-type", "Values": ["interface"]}]
        ).get("NetworkInterfaces", [])
        for eni in enis:
            desc = (eni.get("Description", "") or "").lower()
            groups = " ".join(g.get("GroupName", "") for g in eni.get("Groups", [])).lower()
            if "devlake" in groups or "devlake" in desc or "rdsnetworkinterface" in desc.replace(" ", ""):
                return False
        return True
    except Exception:
        return True


def _c(code):
    return f" ({code})" if code else ""


def reap(ctx):
    """§4. Delete the DevLake Aurora stack (instances → cluster → subnet group) and
    wait for its ENI to drain, so the downstream VPC delete isn't blocked."""
    log, rds = ctx.log, ctx.rds

    instances = _devlake_instances(ctx)
    clusters = _devlake_clusters(ctx)
    if not instances and not clusters:
        log("No DevLake RDS resources to delete")
        return

    # 1) Member / standalone instances first (Aurora: members must be gone before
    #    the cluster can be deleted). Clear deletion-protection defensively.
    for ident in instances:
        try:
            rds.modify_db_instance(DBInstanceIdentifier=ident,
                                   DeletionProtection=False, ApplyImmediately=True)
        except Exception:
            pass
        kind, code, _ = run_delete(lambda i=ident: rds.delete_db_instance(
            DBInstanceIdentifier=i, SkipFinalSnapshot=True, DeleteAutomatedBackups=True))
        log(f"  Deleting RDS instance {ident}: {kind}{_c(code)}")

    # 2) Wait for instances to drain so the cluster delete isn't ResourceInUse
    #    (~15 min ceiling; best-effort — §16 re-sweep is the backstop).
    if instances:
        drained = poll_until(lambda: not _devlake_instances(ctx), attempts=45, delay=20.0)
        if not drained:
            log("DevLake RDS instances still present after wait — cluster delete may requeue")

    # 3) Aurora clusters, now that their members are gone.
    for ident in clusters:
        try:
            rds.modify_db_cluster(DBClusterIdentifier=ident,
                                  DeletionProtection=False, ApplyImmediately=True)
        except Exception:
            pass
        kind, code, _ = run_delete(lambda i=ident: rds.delete_db_cluster(
            DBClusterIdentifier=i, SkipFinalSnapshot=True))
        log(f"  Deleting RDS cluster {ident}: {kind}{_c(code)}")

    # 4) Wait for the Aurora ENI to drain before the VPC reaper / CFN VPC delete
    #    (~10 min ceiling). This is the step that prevents the DependencyViolation.
    if poll_until(lambda: _no_devlake_eni(ctx), attempts=30, delay=20.0):
        log("DevLake RDS ENI drained")
    else:
        log("DevLake RDS ENI still present after wait — §14/§16 backstop will re-drive")

    # 5) DB subnet group (lingers; name-collides on reused accounts, issue #8).
    #    Safe only once the DBs above are gone.
    try:
        for sg in rds.describe_db_subnet_groups().get("DBSubnetGroups", []):
            name = sg["DBSubnetGroupName"]
            if not _is_devlake(name, ctx.prefix):
                continue
            kind, code, _ = run_delete(lambda n=name: rds.delete_db_subnet_group(DBSubnetGroupName=n))
            log(f"  Deleting RDS subnet group {name}: {kind}{_c(code)}")
    except Exception as e:
        log(f"RDS subnet groups: {e}")
