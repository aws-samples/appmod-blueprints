"""RDS reaper (§4): DevLake MySQL DB creates an ENI in the IDE VPC subnets."""


def reap(ctx):
    log, rds = ctx.log, ctx.rds
    try:
        deleted = 0
        for db in rds.describe_db_instances()["DBInstances"]:
            if db["DBInstanceIdentifier"].startswith("devlake"):
                rds.delete_db_instance(
                    DBInstanceIdentifier=db["DBInstanceIdentifier"],
                    SkipFinalSnapshot=True,
                    DeleteAutomatedBackups=True,
                )
                log(f"  Deleting RDS {db['DBInstanceIdentifier']}")
                deleted += 1
        if not deleted:
            log("No RDS instances to delete")
    except Exception as e:
        log(f"RDS: {e}")
