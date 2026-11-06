"""IAM reaper (§7): roles + customer-managed policies left after Terraform destroy.

Skips team-stack / SharedRole (CFN-owned). #914: arbitrarily-named spokes get
roles named after the CLUSTER, so also reap names starting with any discovered spoke.
"""


def reap(ctx):
    log, iam, prefix, spokes = ctx.log, ctx.iam, ctx.prefix, ctx.spokes
    try:
        _skip = ("-team-stack-", "SharedRole")
        _owned_prefixes = [prefix] + [s for s in spokes if not s.startswith(prefix + "-")]

        # CloudFormation names the stack's own roles <stack-name>-<LogicalId>-<random>.
        # The self-paced stack is "<prefix>-workshop" (no "-team-stack-"), so skip that
        # prefix too: deleting those roles breaks the stack's custom resources on delete.
        _stack_prefix = prefix + "-workshop-"

        def _is_owned(name):
            return (
                any(name.startswith(p + "-") for p in _owned_prefixes)
                and not any(x in name for x in _skip)
                and not name.startswith(_stack_prefix)
            )

        # Fixed-name roles outside the prefix (e.g. the HuggingFaceModel <model>-role, which keeps
        # its legacy unprefixed name on the default prefix so existing stacks keep their roles) are
        # owned by TAG, never by name: platform.gitops.io/prefix=<prefix> and no CloudFormation tag.
        # Service-linked roles and the stack's own roles (_skip / _stack_prefix) are never taken.
        def _tag_owned(role):
            nonlocal tag_errors
            n = role["RoleName"]
            if role.get("Path", "/").startswith("/aws-service-role/"):
                return False
            if any(x in n for x in _skip) or n.startswith(_stack_prefix):
                return False
            try:
                tags = {t["Key"]: t["Value"] for t in iam.list_role_tags(RoleName=n).get("Tags", [])}
            except Exception as e:
                tag_errors += 1
                if tag_errors == 1:
                    log(f"  IAM tag check ({n}): {e.__class__.__name__}")
                return False
            return (
                tags.get(ctx.OWNER_PREFIX_TAG) == prefix
                and not any(k.startswith("aws:cloudformation:") for k in tags)
            )

        tag_errors = 0
        count = 0
        for role in sum(
            [p["Roles"] for p in iam.get_paginator("list_roles").paginate()], []
        ):
            n = role["RoleName"]
            if not _is_owned(n) and not _tag_owned(role):
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
        if tag_errors:
            log(f"  IAM: {tag_errors} role tag lookup(s) failed — those roles were left alone")
        log(f"  Deleted {count} IAM roles")

        tag_owned_deleted = 0
        for pol in sum(
            [p["Policies"] for p in iam.get_paginator("list_policies").paginate(Scope="Local")],
            [],
        ):
            n = pol["PolicyName"]
            by_tag = False
            if not _is_owned(n):
                if any(x in n for x in _skip) or n.startswith(_stack_prefix):
                    continue
                if not policy_tag_owned(ctx, pol):
                    continue
                by_tag = True
            try:
                for v in iam.list_policy_versions(PolicyArn=pol["Arn"])["Versions"]:
                    if not v["IsDefaultVersion"]:
                        iam.delete_policy_version(PolicyArn=pol["Arn"], VersionId=v["VersionId"])
                iam.delete_policy(PolicyArn=pol["Arn"])
                if by_tag:
                    tag_owned_deleted += 1
                    log(f"  Deleted IAM policy {n} (owned by tag, no attachment)")
            except Exception:
                pass
        if tag_owned_deleted:
            log(f"  Deleted {tag_owned_deleted} unprefixed IAM policy(ies) owned by tag")
    except Exception as e:
        log(f"IAM: {e}")


def policy_tag_owned(ctx, pol):
    """A customer-managed policy whose NAME is outside our prefix (the HuggingFaceModel
    <model>-s3-policy keeps its legacy unprefixed name on the default prefix) is ours only
    when BOTH hold:
      * it carries platform.gitops.io/prefix=<prefix>, or it was created by OUR hub's ACK
        capability (eks:eks-capability-arn naming exactly <prefix>-hub), and no
        aws:cloudformation:* tag;
      * it is attached to nothing (AttachmentCount 0): a fixed name can be adopted by a
        second stack in the account (adopt-or-create), and a policy still attached may be
        that stack's, so it is never taken.
    The live listing's AttachmentCount is used; a failed tag lookup means "not ours"."""
    if pol.get("AttachmentCount", 1) != 0:
        return False
    try:
        tags = {t["Key"]: t["Value"]
                for t in ctx.iam.list_policy_tags(PolicyArn=pol["Arn"]).get("Tags", [])}
    except Exception:
        return False
    if any(k.startswith("aws:cloudformation:") for k in tags):
        return False
    if tags.get(ctx.OWNER_PREFIX_TAG) == ctx.prefix:
        return True
    cap = tags.get("eks:eks-capability-arn", "")
    return ":capability/" in cap and cap.split(":capability/", 1)[1].split("/", 1)[0] == ctx.hub


def owned_orphan_policies(ctx):
    """Names of the unprefixed, tag-owned, unattached policies still present (§17)."""
    out = []
    for p in ctx.iam.get_paginator("list_policies").paginate(Scope="Local"):
        for pol in p.get("Policies", []):
            n = pol["PolicyName"]
            if n.startswith(ctx.prefix + "-"):
                continue  # prefix-named: deleted by name in §7 (not re-checked here)
            if policy_tag_owned(ctx, pol):
                out.append(n)
    return out
