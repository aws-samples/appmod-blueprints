"""Completeness verification + re-drive (§17, #932).

(a) Re-drives resource classes that depend on an earlier ASYNC deletion (NAT-EIP
release after the VPC reaper, idempotent ECR / log-group deletes), then
(b) enumerates everything still carrying the ownership tag / prefix and returns
the residue list. The orchestrator turns a non-empty residue into a non-zero exit
(unless SWEEP_ALLOW_RESIDUE) so a strict caller can flag an incomplete teardown.
"""


def run(ctx):
    """Returns the list of residual owned-resource tokens (empty == DESTROY COMPLETE)."""
    log = ctx.log
    ec2, ecr, logs, eks, s3, sm = ctx.ec2, ctx.ecr, ctx.logs, ctx.eks, ctx.s3, ctx.sm
    prefix, hub, region = ctx.prefix, ctx.hub, ctx.region
    OWNER_PREFIX_TAG = ctx.OWNER_PREFIX_TAG

    residue = []
    try:
        # 17a. Re-release NAT EIPs freed by the VPC reaper (they were still
        #      "associated" when §13 ran, so they were skipped then).
        try:
            for a in ec2.describe_addresses().get("Addresses", []):
                if a.get("AssociationId"):
                    continue
                tags = {t["Key"]: t["Value"] for t in a.get("Tags", [])}
                if tags.get(OWNER_PREFIX_TAG) == prefix or any(prefix in str(v) for v in tags.values()):
                    try:
                        ec2.release_address(AllocationId=a["AllocationId"])
                        log(f"  [verify] Released freed EIP {a.get('PublicIp')}")
                    except Exception as e:
                        log(f"  [verify] EIP {a.get('PublicIp')}: {e.__class__.__name__}")
        except Exception as e:
            log(f"  [verify] EIP re-release: {e}")

        # 17b. Idempotent re-drive of the imperatively-created ECR repo + owned log groups.
        try:
            ecr.delete_repository(repositoryName=f"{prefix}-ray-vllm-custom", force=True)
            log(f"  [verify] Deleted lingering ECR repo {prefix}-ray-vllm-custom")
        except Exception:
            pass
        try:
            for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=f"/aws/eks/{prefix}"):
                for lg in page["logGroups"]:
                    try:
                        logs.delete_log_group(logGroupName=lg["logGroupName"])
                        log(f"  [verify] Deleted lingering log group {lg['logGroupName']}")
                    except Exception:
                        pass
        except Exception:
            pass

        # 17c. Enumerate remaining owned resources (never the CFN-owned IDE VPC).
        def _add(tok):
            if tok not in residue:
                residue.append(tok)

        try:  # EKS clusters (hub + tagged spokes)
            for name in sum([p.get("clusters", []) for p in eks.get_paginator("list_clusters").paginate()], []):
                if name == hub:
                    _add(f"eks-cluster:{name}")
                else:
                    try:
                        if eks.describe_cluster(name=name)["cluster"].get("tags", {}).get(OWNER_PREFIX_TAG) == prefix:
                            _add(f"eks-cluster:{name}")
                    except Exception:
                        pass
        except Exception:
            pass
        try:  # spoke / owned VPCs
            for flt in (
                {"Name": "tag:eks:kubernetes-resource-name",
                 "Values": [f"{prefix}-spoke-dev-vpc", f"{prefix}-spoke-prod-vpc"]},
                {"Name": "tag:Name", "Values": [f"{prefix}-spoke-*-vpc"]},
                {"Name": f"tag:{OWNER_PREFIX_TAG}", "Values": [prefix]},
            ):
                for v in ec2.describe_vpcs(Filters=[flt]).get("Vpcs", []):
                    if any(t["Key"].startswith("aws:cloudformation:") for t in v.get("Tags", [])):
                        continue
                    _add(f"vpc:{v['VpcId']}")
        except Exception:
            pass
        try:  # unassociated prefixed EIPs
            for a in ec2.describe_addresses().get("Addresses", []):
                if a.get("AssociationId"):
                    continue
                tags = {t["Key"]: t["Value"] for t in a.get("Tags", [])}
                if tags.get(OWNER_PREFIX_TAG) == prefix or any(prefix in str(v) for v in tags.values()):
                    _add(f"eip:{a.get('PublicIp')}")
        except Exception:
            pass
        try:  # imperatively-created ECR repo
            ecr.describe_repositories(repositoryNames=[f"{prefix}-ray-vllm-custom"])
            _add(f"ecr:{prefix}-ray-vllm-custom")
        except Exception:
            pass
        try:  # prefixed S3 buckets in this region
            for b in s3.list_buckets().get("Buckets", []):
                if not b["Name"].startswith(prefix + "-"):
                    continue
                try:
                    loc = s3.get_bucket_location(Bucket=b["Name"]).get("LocationConstraint") or "us-east-1"
                except Exception:
                    loc = region
                if loc == region:
                    _add(f"s3:{b['Name']}")
        except Exception:
            pass
        try:  # owned control-plane log groups
            for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=f"/aws/eks/{prefix}"):
                for lg in page["logGroups"]:
                    _add(f"log-group:{lg['logGroupName']}")
        except Exception:
            pass
        try:  # active + scheduled-for-deletion prefixed secrets
            for _p in sm.get_paginator("list_secrets").paginate(
                IncludePlannedDeletion=True, Filters=[{"Key": "name", "Values": [prefix]}]
            ):
                for s in _p.get("SecretList", []):
                    _add(f"secret:{s['Name']}")
        except Exception:
            pass

        if residue:
            log(f"DESTROY INCOMPLETE — {len(residue)} owned resource(s) still present:")
            for r in residue:
                log(f"  ✗ {r}")
        else:
            log("DESTROY COMPLETE — no owned (tagged/prefixed) resources remain")
    except Exception as e:
        log(f"Completeness verification: {e}")

    return residue
