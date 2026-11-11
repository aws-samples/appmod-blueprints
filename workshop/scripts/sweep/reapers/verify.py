"""Completeness verification + re-drive (§17, #932).

(a) Re-drives resource classes that depend on an earlier ASYNC deletion (NAT-EIP
release after the VPC reaper, idempotent ECR / log-group deletes), then
(b) enumerates everything still carrying the ownership tag / prefix and returns
the residue list. The orchestrator turns a non-empty residue into a non-zero exit
(unless SWEEP_ALLOW_RESIDUE) so a strict caller can flag an incomplete teardown.
"""

from ..context import name_is_ours
from . import amp as amp_reaper
from . import grafana as grafana_reaper
from . import iam as iam_reaper
from . import oidc as oidc_reaper
from . import residue as residue_reaper
from .logs import log_group_is_ours
from .s3 import _code as _s3_code
from .s3 import cfn_owner


def _tagged_arn_exists(ctx, arn):
    """Re-check a tag-index hit for the types whose tag index lags (EBS volumes). Anything
    else, or a check that cannot decide, counts as existing: the gate never hides residue."""
    parts = arn.split(":", 5)
    if len(parts) == 6 and parts[2] == "ec2" and parts[5].startswith("volume/"):
        return residue_reaper.still_exists(ctx, "ebs", parts[5].split("/", 1)[1])
    return True


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
                if ctx.eip_is_ours(tags):
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
                    if not log_group_is_ours(lg["logGroupName"], prefix):
                        continue  # another stack whose prefix starts with ours (#1111)
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
        # Security groups left in the IDE VPC that CloudFormation does not own, tagged by us
        # or not (the AMG workspace SG carries no prefix tag): CFN cannot delete the VPC
        # while one remains, so the gate must not say DESTROY COMPLETE.
        try:
            ide_vpc = ctx.find_ide_vpc("[verify] ")
            if ide_vpc:
                left = ctx.leftover_vpc_sgs(ide_vpc)
                if left is None:
                    log(f"  [verify] cannot list the security groups of IDE VPC {ide_vpc}")
                for sg in left or []:
                    _add(f"sg:{ide_vpc}/{sg}")
        except Exception as e:
            log(f"  [verify] IDE VPC security groups: {e}")
        try:  # IAM OIDC providers of our deleted clusters (no prefix tag: 17d misses them)
            for arn in oidc_reaper.owned_providers(ctx) or []:
                _add(f"oidc-provider:{arn.rsplit('/', 1)[-1]}")
        except Exception as e:
            log(f"  [verify] OIDC providers: {e}")
        try:  # unprefixed IAM policies we own by tag and nothing uses (HuggingFaceModel)
            for n in iam_reaper.owned_orphan_policies(ctx):
                _add(f"iam-policy:{n}")
        except Exception as e:
            log(f"  [verify] IAM policies: {e}")
        # AMP / AMG workspaces: Crossplane tags them without the prefix tag, so 17d misses
        # one a still-running hub Crossplane re-created after the sweep deleted it.
        try:
            for ws in amp_reaper.owned_workspaces(ctx):
                _add(f"amp-workspace:{ws['workspaceId']}({ws.get('alias')})")
        except Exception as e:
            log(f"  [verify] AMP workspaces: {e.__class__.__name__}")
        try:
            for ws in grafana_reaper.owned_workspaces(ctx):
                _add(f"amg-workspace:{ws['id']}({ws.get('name')})")
        except Exception as e:
            log(f"  [verify] AMG workspaces: {e.__class__.__name__}")
        try:  # unassociated prefixed EIPs
            for a in ec2.describe_addresses().get("Addresses", []):
                if a.get("AssociationId"):
                    continue
                tags = {t["Key"]: t["Value"] for t in a.get("Tags", [])}
                if ctx.eip_is_ours(tags):
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
                if loc != region:
                    continue
                # CloudFormation-owned buckets are left to CloudFormation by the S3 reaper
                # (same tag test), so they are not residue. Unreadable tags: the reaper left
                # the bucket alone, so it still counts.
                try:
                    if cfn_owner(s3, b["Name"]):
                        continue
                except Exception as e:
                    if _s3_code(e) == "NoSuchBucket":
                        continue
                _add(f"s3:{b['Name']}")
        except Exception:
            pass
        try:  # owned control-plane log groups
            for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=f"/aws/eks/{prefix}"):
                for lg in page["logGroups"]:
                    if log_group_is_ours(lg["logGroupName"], prefix):
                        _add(f"log-group:{lg['logGroupName']}")
        except Exception:
            pass
        try:  # active + scheduled-for-deletion prefixed secrets
            for _p in sm.get_paginator("list_secrets").paginate(
                IncludePlannedDeletion=True, Filters=[{"Key": "name", "Values": [prefix]}]
            ):
                for s in _p.get("SecretList", []):
                    if name_is_ours(s["Name"], prefix):
                        _add(f"secret:{s['Name']}")
        except Exception:
            pass

        # 17d. Authoritative completeness gate (appmod-blueprints#924). Enumerate everything
        #      still carrying platform.gitops.io/prefix=<prefix> via the Resource Groups
        #      Tagging API — the one ownership key stamped on Layer 1 (CDK/CFN) AND Layer 2/3
        #      (kro/ACK) resources. The §16b final-net reaper already DELETED the out-of-CFN
        #      orphans it found, so this gate now CONFIRMS that work: anything still returned
        #      here is genuine residue (undeletable, access-denied, or an unhandled type the
        #      net left behind). It also catches out-of-CFN residue the prefix/cluster scans
        #      above may miss (arbitrarily-named resources). CAVEATS (why it SUPPLEMENTS, not
        #      replaces, the per-service scans): (1) the tagging API is regional, so global
        #      resources (CloudFront) never appear here; (2) AWS-created resources (Auto
        #      Mode ENIs, RDS-managed SGs) don't carry our tag. EXCLUSION: resources that
        #      also carry aws:cloudformation:* tags are Layer 1 CFN-managed (the IDE VPC/
        #      EC2/CodeBuild) — CloudFormation deletes those itself AFTER the sweep, so
        #      counting them here would make the gate a permanent false-positive.
        try:
            for arn, tags in ctx.discover_by_tag():
                if any(k.startswith("aws:cloudformation:") for k in tags):
                    continue  # Layer 1, CloudFormation reaps it after the sweep
                # The tagging API is eventually consistent: it can still return a resource
                # that is already deleted (a PVC volume, R-27). Look it up before counting it.
                if not _tagged_arn_exists(ctx, arn):
                    log(f"  [verify] {arn} no longer exists (stale tag index), not counted")
                    continue
                _add(f"tagged:{arn}")
        except Exception as e:
            log(f"  [verify] {ctx.OWNER_PREFIX_TAG} gate: {e}")

        # 17e. App-layer families that carry no ownership tag the gate can enumerate
        #      (R-27): PVC volumes, ECR <prefix>/*, DynamoDB <prefix>-*, SSM /<prefix>/*,
        #      fluent-bit log groups. Same listers as the §16c net; each hit is looked up
        #      again so a resource deleted since the listing is not reported.
        found, errors = residue_reaper.enumerate_families(ctx)
        for fam, err in errors.items():
            log(f"  [verify] cannot list {fam} residue ({err})")
        for fam, idents in found.items():
            for ident in idents:
                if residue_reaper.still_exists(ctx, fam, ident):
                    _add(f"{fam}:{ident}")
                else:
                    log(f"  [verify] {fam}:{ident} no longer exists, not counted")
        if residue:
            log(f"DESTROY INCOMPLETE — {len(residue)} owned resource(s) still present:")
            for r in residue:
                log(f"  ✗ {r}")
        else:
            log("DESTROY COMPLETE — no owned (tagged/prefixed) resources remain")
    except Exception as e:
        log(f"Completeness verification: {e}")

    return residue
