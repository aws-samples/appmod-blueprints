"""IAM reaper (§7): roles + customer-managed policies left after Terraform destroy.

Skips team-stack / SharedRole (CFN-owned). #914: arbitrarily-named spokes get
roles named after the CLUSTER, so also reap names starting with any discovered spoke.
"""


def reap(ctx):
    log, iam, prefix, spokes = ctx.log, ctx.iam, ctx.prefix, ctx.spokes
    try:
        _skip = ("-team-stack-", "SharedRole")
        _owned_prefixes = [prefix] + [s for s in spokes if not s.startswith(prefix + "-")]

        def _is_owned(name):
            return any(name.startswith(p + "-") for p in _owned_prefixes) and not any(
                x in name for x in _skip
            )

        count = 0
        for role in sum(
            [p["Roles"] for p in iam.get_paginator("list_roles").paginate()], []
        ):
            n = role["RoleName"]
            if not _is_owned(n):
                continue
            try:
                for pol in iam.list_attached_role_policies(RoleName=n)["AttachedPolicies"]:
                    iam.detach_role_policy(RoleName=n, PolicyArn=pol["PolicyArn"])
                for ip in iam.list_role_policies(RoleName=n)["PolicyNames"]:
                    iam.delete_role_policy(RoleName=n, PolicyName=ip)
                iam.delete_role(RoleName=n)
                count += 1
            except Exception:
                pass
        log(f"  Deleted {count} IAM roles")

        for pol in sum(
            [p["Policies"] for p in iam.get_paginator("list_policies").paginate(Scope="Local")],
            [],
        ):
            n = pol["PolicyName"]
            if not _is_owned(n):
                continue
            try:
                for v in iam.list_policy_versions(PolicyArn=pol["Arn"])["Versions"]:
                    if not v["IsDefaultVersion"]:
                        iam.delete_policy_version(PolicyArn=pol["Arn"], VersionId=v["VersionId"])
                iam.delete_policy(PolicyArn=pol["Arn"])
            except Exception:
                pass
    except Exception as e:
        log(f"IAM: {e}")
