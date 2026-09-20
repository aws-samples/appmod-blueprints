#!/usr/bin/env python3
"""
sweep-workshop-resources.py — Extended AWS resource sweep for workshop teardown.

Called by the ClustersStackDeploy CodeBuild after `workshop/task destroy` completes,
to remove resources that persist after task destroy and would block VPC subnet deletion
when CloudFormation tries to clean up the IDE VPC.

Usage:
    python3 sweep-workshop-resources.py <region> <resource_prefix>

    region          AWS region (e.g. us-west-2)
    resource_prefix Workshop resource prefix (e.g. peeks)

Exit code is always 0 — failures are logged but never fatal, since the CFN
deletion must continue regardless.
"""

import boto3
import sys
import time

region = sys.argv[1] if len(sys.argv) > 1 else "us-west-2"
prefix = sys.argv[2] if len(sys.argv) > 2 else "peeks"
hub = f"{prefix}-hub"

eks = boto3.client("eks", region_name=region)
iam = boto3.client("iam")
ec2 = boto3.client("ec2", region_name=region)
elbv2 = boto3.client("elbv2", region_name=region)
rds = boto3.client("rds", region_name=region)
amp = boto3.client("amp", region_name=region)
sm = boto3.client("secretsmanager", region_name=region)
logs = boto3.client("logs", region_name=region)
cf = boto3.client("cloudfront")
grafana = boto3.client("grafana", region_name=region)
ecr = boto3.client("ecr", region_name=region)
s3 = boto3.client("s3")


def log(msg):
    print(f"[sweep] {msg}", flush=True)


hub_vpc_id = None

# PR #914 makes spoke names arbitrary (no longer guaranteed to be
# <prefix>-spoke-dev / <prefix>-spoke-prod) and stamps every workshop-owned EKS
# cluster and VPC with the ownership tag platform.gitops.io/prefix=<prefix>.
# Discover spokes by that tag so arbitrarily-named spokes (e.g. "oap-test") are
# reaped too — unioned with the legacy name pattern so the sweep still works on
# environments deployed before #914 (where the tag may be absent).
OWNER_PREFIX_TAG = "platform.gitops.io/prefix"


def _discover_spokes():
    """Union of the legacy spoke name pattern and every non-hub EKS cluster
    carrying platform.gitops.io/prefix=<prefix> (#914 ownership tag)."""
    found = {f"{prefix}-spoke-dev", f"{prefix}-spoke-prod"}
    try:
        for page in eks.get_paginator("list_clusters").paginate():
            for name in page.get("clusters", []):
                if name == hub:
                    continue
                try:
                    tags = eks.describe_cluster(name=name)["cluster"].get("tags", {})
                except Exception:
                    continue
                if tags.get(OWNER_PREFIX_TAG) == prefix:
                    found.add(name)
                    log(f"  Discovered owned spoke by tag: {name}")
    except Exception as e:
        log(f"Spoke discovery: {e}")
    return sorted(found)


spokes = _discover_spokes()


def _revoke_sg_rules(sg):
    """Revoke a security group's ingress/egress rules so circular SG references
    (e.g. eks-cluster-sg ↔ k8s-traffic-*) don't block deletion."""
    gid = sg["GroupId"]
    if sg.get("IpPermissions"):
        try:
            ec2.revoke_security_group_ingress(GroupId=gid, IpPermissions=sg["IpPermissions"])
        except Exception:
            pass
    if sg.get("IpPermissionsEgress"):
        try:
            ec2.revoke_security_group_egress(GroupId=gid, IpPermissions=sg["IpPermissionsEgress"])
        except Exception:
            pass


def _delete_vpc_sgs(vpc_id):
    """Delete every non-default, non-CloudFormation-owned security group in a VPC.
    Two passes (revoke all rules, then delete all) to survive circular references.
    Leaves CFN-owned SGs (aws:cloudformation:* tag) and the VPC itself untouched.
    Returns the number of SGs deleted."""
    try:
        sgs = [
            s for s in ec2.describe_security_groups(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )["SecurityGroups"]
            if s["GroupName"] != "default"
            and not any(t["Key"].startswith("aws:cloudformation:") for t in s.get("Tags", []))
        ]
    except Exception:
        return 0
    for s in sgs:
        _revoke_sg_rules(s)
    deleted = 0
    for s in sgs:
        try:
            ec2.delete_security_group(GroupId=s["GroupId"])
            deleted += 1
        except Exception:
            pass
    return deleted


# ---------------------------------------------------------------------------
# 1. EKS Capabilities
#    Must be deleted before aws eks delete-cluster, otherwise delete-cluster
#    fails with "cluster has active capabilities".
# ---------------------------------------------------------------------------
try:
    caps = eks.list_capabilities(clusterName=hub).get("capabilities", [])
    if caps:
        log(f"Deleting {len(caps)} EKS capabilities ({', '.join(c['capabilityName'] for c in caps)})...")
        for cap in caps:
            try:
                eks.delete_capability(clusterName=hub, capabilityName=cap["capabilityName"])
            except Exception:
                pass
        for i in range(20):
            remaining = eks.list_capabilities(clusterName=hub).get("capabilities", [])
            if not remaining:
                log("  Capabilities cleared")
                break
            time.sleep(15)
    else:
        log("No EKS capabilities to delete")
except Exception as e:
    log(f"Capabilities: {e}")


# ---------------------------------------------------------------------------
# 2. CloudFront VPC Origin + Distribution
#    The VPC Origin keeps a cloudfront_managed ENI in the IDE VPC subnets.
#    Distribution must be disabled then deleted before VPC Origin can be removed.
# ---------------------------------------------------------------------------
try:
    vos = cf.list_vpc_origins().get("VpcOriginList", {}).get("Items", [])
    vo_ids = {vo["Id"] for vo in vos if vo.get("Name", "").startswith(hub + "-")}

    dist_ids = set()
    dists = cf.list_distributions().get("DistributionList", {}).get("Items", [])
    for d in dists:
        if d.get("Comment", "").startswith(hub):
            dist_ids.add(d["Id"])
            continue
        for o in d.get("Origins", {}).get("Items", []):
            if o.get("VpcOriginConfig", {}).get("VpcOriginId", "") in vo_ids:
                dist_ids.add(d["Id"])

    for dist_id in dist_ids:
        resp = cf.get_distribution_config(Id=dist_id)
        etag, cfg = resp["ETag"], resp["DistributionConfig"]
        if cfg.get("Enabled", True):
            cfg["Enabled"] = False
            cf.update_distribution(Id=dist_id, DistributionConfig=cfg, IfMatch=etag)
            log(f"  Disabling CF distribution {dist_id} (waiting for Deployed)...")
            for _ in range(20):
                if cf.get_distribution(Id=dist_id)["Distribution"]["Status"] == "Deployed":
                    break
                time.sleep(15)
        etag2 = cf.get_distribution(Id=dist_id)["ETag"]
        cf.delete_distribution(Id=dist_id, IfMatch=etag2)
        log(f"  Deleted CF distribution {dist_id}")

    # Small delay so ENIs detach before VPC Origin deletion
    if dist_ids:
        time.sleep(5)

    for vo_id in vo_ids:
        etag = cf.get_vpc_origin(Id=vo_id)["ETag"]
        cf.delete_vpc_origin(Id=vo_id, IfMatch=etag)
        log(f"  Deleted CF VPC origin {vo_id}")

    if not dist_ids and not vo_ids:
        log("No CloudFront distributions/VPC origins to delete")
except Exception as e:
    log(f"CloudFront: {e}")


# ---------------------------------------------------------------------------
# 3. ALBs
#    The hub platform ALB (peeks-hub-platform) creates ENIs in IDE VPC subnets.
# ---------------------------------------------------------------------------
try:
    deleted = 0
    for lb in elbv2.describe_load_balancers()["LoadBalancers"]:
        if lb["LoadBalancerName"].startswith(prefix + "-"):
            elbv2.delete_load_balancer(LoadBalancerArn=lb["LoadBalancerArn"])
            log(f"  Deleted ALB {lb['LoadBalancerName']}")
            deleted += 1
    if not deleted:
        log("No ALBs to delete")
except Exception as e:
    log(f"ALBs: {e}")


# ---------------------------------------------------------------------------
# 4. RDS instances
#    DevLake MySQL DB creates an ENI in the IDE VPC subnets.
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 5. AMP scrapers + workspaces
#    AMP managed scrapers create amp_collector ENIs in VPC subnets. These ENIs
#    can persist for 5+ minutes after scraper deletion, blocking subnet deletion.
# ---------------------------------------------------------------------------
try:
    scrapers = amp.list_scrapers().get("scrapers", [])
    for s in scrapers:
        try:
            amp.delete_scraper(scraperId=s["scraperId"])
            log(f"  Deleted AMP scraper {s['scraperId']}")
        except Exception:
            pass
    for ws in amp.list_workspaces()["workspaces"]:
        if ws.get("alias", "").startswith(prefix):
            try:
                amp.delete_workspace(workspaceId=ws["workspaceId"])
            except Exception:
                pass
    if not scrapers:
        log("No AMP scrapers to delete")
except Exception as e:
    log(f"AMP: {e}")


# ---------------------------------------------------------------------------
# 6. Hub EKS cluster (direct AWS API delete, bypasses KRO)
#    workshop/task destroy (kind-kro-ack) kills the Kind cluster first, which
#    removes the KRO controller. Without KRO the EksCluster CR is never
#    reconciled for deletion — we must delete directly via AWS API.
#    Waits up to 15 minutes for the cluster to be gone before continuing,
#    so that Auto Mode ENIs are fully released from the IDE VPC subnets.
# ---------------------------------------------------------------------------
try:
    _hub = eks.describe_cluster(name=hub)["cluster"]
    cluster_status = _hub["status"]
    hub_vpc_id = _hub.get("resourcesVpcConfig", {}).get("vpcId") or hub_vpc_id
    if cluster_status != "DELETING":
        eks.delete_cluster(name=hub)
        log("  Hub EKS cluster deletion submitted")
    else:
        log("  Hub EKS cluster already DELETING")
    # Wait up to 15 min (30 × 30 s)
    final_status = "DELETING"
    for i in range(30):
        try:
            final_status = eks.describe_cluster(name=hub)["cluster"]["status"]
        except eks.exceptions.ResourceNotFoundException:
            final_status = "NOT_FOUND"
            break
        if i % 5 == 0:
            log(f"  [{i + 1}/30] Hub EKS: {final_status}")
        time.sleep(30)
    log(f"  Hub EKS: {'deleted' if final_status == 'NOT_FOUND' else final_status}")
except eks.exceptions.ResourceNotFoundException:
    log("  Hub EKS cluster already gone")
except Exception as e:
    log(f"Hub EKS: {e}")


# ---------------------------------------------------------------------------
# 6b. Orphaned spoke EKS clusters
#     If `task destroy` was cut short (e.g. the CFN Delete path did not wait for
#     it to finish), the KRO/ACK-provisioned spoke clusters can remain ACTIVE.
#     Nothing else reaps them, and their VPCs (sections 10/14) cannot be deleted
#     while the cluster is alive. Delete capabilities first, then the clusters,
#     then wait for all to be gone (Auto Mode releases ENIs on cluster delete).
# ---------------------------------------------------------------------------
try:
    pending = []
    for spoke in spokes:
        try:
            s_status = eks.describe_cluster(name=spoke)["cluster"]["status"]
        except eks.exceptions.ResourceNotFoundException:
            continue
        except Exception as e:
            log(f"  Spoke {spoke}: {e}")
            continue
        for cap in eks.list_capabilities(clusterName=spoke).get("capabilities", []):
            try:
                eks.delete_capability(clusterName=spoke, capabilityName=cap["capabilityName"])
            except Exception:
                pass
        pending.append(spoke)
    for spoke in pending:  # retry delete_cluster until capabilities finish deleting
        # ACK capabilities can take ~15-20 min to finish DELETING; delete_cluster fails
        # with ResourceInUseException ("Cluster has capabilities attached") until they
        # clear. A single attempt after a fixed short wait (the old 5 min) races ACK and
        # leaves the spoke orphaned. Retry delete_cluster (up to ~25 min) instead: as soon
        # as the capabilities clear the call succeeds.
        submitted = False
        for i in range(100):  # ~25 min (100 × 15s)
            try:
                if eks.describe_cluster(name=spoke)["cluster"]["status"] == "DELETING":
                    submitted = True
                    break
            except eks.exceptions.ResourceNotFoundException:
                submitted = True
                break
            except Exception:
                pass
            try:
                eks.delete_cluster(name=spoke)
                log(f"  Spoke {spoke} deletion submitted")
                submitted = True
                break
            except eks.exceptions.ResourceNotFoundException:
                submitted = True
                break
            except Exception as e:
                # Typically ResourceInUseException while capabilities are still DELETING.
                if i % 8 == 0:
                    log(f"  Spoke {spoke}: waiting for capabilities to clear before delete ({e.__class__.__name__})")
                time.sleep(15)
        if not submitted:
            log(f"  Spoke {spoke}: delete still blocked after ~25 min — leaving for the next sweep")
    for spoke in pending:  # wait up to ~15 min per spoke for full deletion
        for _ in range(30):
            try:
                eks.describe_cluster(name=spoke)
            except eks.exceptions.ResourceNotFoundException:
                log(f"  Spoke {spoke}: deleted")
                break
            except Exception:
                break
            time.sleep(30)
    if not pending:
        log("No orphaned spoke clusters to delete")
except Exception as e:
    log(f"Orphaned spoke clusters: {e}")


# ---------------------------------------------------------------------------
# 7. IAM roles + customer-managed policies
#    task destroy removes most IAM resources via Terraform, but some roles
#    created directly (peeks-cluster-mgmt-*, peeks-hub-cluster-*) may remain.
#    Skip team-stack and SharedRole resources owned by CFN itself.
#    #914: arbitrarily-named spokes get roles named after the CLUSTER (e.g.
#    oap-test-cluster-role), which do NOT start with the resource prefix — so
#    also reap names starting with any discovered spoke name.
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 8. Secrets Manager
#    Workshop secrets (peeks/*) that may survive task destroy.
# ---------------------------------------------------------------------------
try:
    # IncludePlannedDeletion=True is critical: a secret already SCHEDULED for
    # deletion (from a prior teardown that used the default recovery window — e.g.
    # the ACK-managed <cluster>/config secrets) is INVISIBLE to a normal
    # list_secrets, yet its name stays reserved for the whole recovery window and
    # blocks the next deploy's CreateSecret ("a secret with this name is already
    # scheduled for deletion"). Force-delete active AND scheduled ones so redeploys
    # on a reused account are not blocked.
    _reaped = 0
    _secret_names = [prefix] + [s for s in spokes if not s.startswith(prefix + "-")]
    for _page in sm.get_paginator("list_secrets").paginate(
        IncludePlannedDeletion=True,
        Filters=[{"Key": "name", "Values": _secret_names}],
    ):
        for s in _page.get("SecretList", []):
            try:
                sm.delete_secret(SecretId=s["ARN"], ForceDeleteWithoutRecovery=True)
                _reaped += 1
            except Exception:
                pass
    log(f"Secrets Manager: force-deleted {_reaped} secret(s) (incl. scheduled-for-deletion)")
except Exception as e:
    log(f"Secrets Manager: {e}")


# ---------------------------------------------------------------------------
# 8b. ECR repositories (imperatively-created, NOT ACK-managed)
#     The Ray/vLLM module builds a custom inference image and pushes it to an
#     ECR repo created imperatively by the Ray build Task
#     (cluster-providers/common/Taskfile.ray.yaml: `aws ecr create-repository
#     <prefix>-ray-vllm-custom`). Unlike the app-layer repos (e.g. <prefix>/rust,
#     <prefix>/java) which are ACK-managed via the CICDPipeline RGD and get
#     cascade-deprovisioned on teardown, this repo has no owning CR, so
#     `task destroy` leaves it behind (a confirmed orphan on reused accounts).
#     Force-delete it (removes any images too).
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 8c. S3 buckets (imperatively-created, NOT part of the CFN stack)
#     The Ray/vLLM module creates a model-cache bucket imperatively
#     (Taskfile.ray.yaml: `<prefix>-ray-models-<accountId>`; the workshop
#     Taskfile variant uses `<hub>-ray-models-<accountId>`), same unowned class
#     as the ECR repo in 8b — `task destroy` never removes it, so it lingers
#     (2+ GB of model artifacts, billing) on reused accounts. Reap every bucket
#     whose name starts with the resource prefix (covers both ray-models shapes
#     and the self-serve `<prefix>-workshop-*` deploy-staging bucket). This is
#     prefix-scoped, so shared bootstrap buckets (cdk-hnb659fds-*, ws-assets-*)
#     are never matched. Empties all object versions + delete markers first.
# ---------------------------------------------------------------------------
try:
    def _empty_bucket(bkt):
        paginator = s3.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bkt):
            batch = [
                {"Key": o["Key"], "VersionId": o["VersionId"]}
                for o in (page.get("Versions", []) + page.get("DeleteMarkers", []))
            ]
            for i in range(0, len(batch), 1000):
                try:
                    s3.delete_objects(Bucket=bkt, Delete={"Objects": batch[i:i + 1000], "Quiet": True})
                except Exception:
                    pass
        # Fallback for non-versioned buckets
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bkt):
            batch = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            for i in range(0, len(batch), 1000):
                try:
                    s3.delete_objects(Bucket=bkt, Delete={"Objects": batch[i:i + 1000], "Quiet": True})
                except Exception:
                    pass

    _reaped = 0
    for b in s3.list_buckets().get("Buckets", []):
        name = b["Name"]
        if not name.startswith(prefix + "-"):
            continue
        # Only touch buckets in this sweep's region (or us-east-1 global-style).
        try:
            loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
        except Exception:
            loc = region
        if loc != region:
            continue
        try:
            _empty_bucket(name)
            s3.delete_bucket(Bucket=name)
            _reaped += 1
            log(f"  Deleted S3 bucket {name}")
        except Exception as e:
            log(f"  S3 {name}: {e}")
    log(f"S3: deleted {_reaped} orphaned bucket(s)" if _reaped else "No orphaned S3 buckets to delete")
except Exception as e:
    log(f"S3: {e}")


# ---------------------------------------------------------------------------
# 9. CloudWatch Log Groups
#    EKS control-plane log groups survive cluster deletion and should be removed.
# ---------------------------------------------------------------------------
try:
    clusters_for_logs = [hub] + spokes
    lg_prefixes = (
        [f"/aws/eks/{c}" for c in clusters_for_logs]
        + [f"/aws/containerinsights/{c}" for c in clusters_for_logs]
        + [f"/aws/lambda/{prefix}-"]
    )
    _lg_deleted = 0
    for pfx in lg_prefixes:
        for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=pfx):
            for lg in page["logGroups"]:
                try:
                    logs.delete_log_group(logGroupName=lg["logGroupName"])
                    _lg_deleted += 1
                except Exception:
                    pass
    log(f"CloudWatch: deleted {_lg_deleted} log group(s)" if _lg_deleted else "No log groups to delete")
except Exception as e:
    log(f"CloudWatch: {e}")


# ---------------------------------------------------------------------------
# 10. Spoke VPCs
#     ACK (kind-kro-ack) and Crossplane (kind-crossplane) create dedicated VPCs
#     for spoke clusters, tagged with eks:kubernetes-resource-name. These are
#     not part of the IDE CFN stack and must be deleted separately.
# ---------------------------------------------------------------------------
try:
    spoke_vpcs = ec2.describe_vpcs(
        Filters=[
            {
                "Name": "tag:eks:kubernetes-resource-name",
                "Values": [
                    f"{prefix}-spoke-dev-vpc",
                    f"{prefix}-spoke-prod-vpc",
                ],
            }
        ]
    )["Vpcs"]

    for v in spoke_vpcs:
        vpc_id = v["VpcId"]
        # Internet Gateways
        for igw in ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )["InternetGateways"]:
            try:
                ec2.detach_internet_gateway(
                    InternetGatewayId=igw["InternetGatewayId"], VpcId=vpc_id
                )
                ec2.delete_internet_gateway(InternetGatewayId=igw["InternetGatewayId"])
            except Exception:
                pass
        # Subnets
        for sn in ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["Subnets"]:
            try:
                ec2.delete_subnet(SubnetId=sn["SubnetId"])
            except Exception:
                pass
        # Route Tables (non-main)
        for rt in ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["RouteTables"]:
            if any(a.get("Main", False) for a in rt.get("Associations", [])):
                continue
            for a in rt.get("Associations", []):
                if not a.get("Main", False) and a.get("RouteTableAssociationId"):
                    try:
                        ec2.disassociate_route_table(
                            AssociationId=a["RouteTableAssociationId"]
                        )
                    except Exception:
                        pass
            try:
                ec2.delete_route_table(RouteTableId=rt["RouteTableId"])
            except Exception:
                pass
        # Security Groups (non-default) — revoke rules first (circular refs)
        _delete_vpc_sgs(vpc_id)
        # VPC
        try:
            ec2.delete_vpc(VpcId=vpc_id)
            log(f"  Deleted spoke VPC {vpc_id}")
        except Exception as e:
            log(f"  Spoke VPC {vpc_id}: {e}")

    if not spoke_vpcs:
        log("No spoke VPCs to delete")
except Exception as e:
    log(f"Spoke VPCs: {e}")


# ---------------------------------------------------------------------------
# 11. Amazon Managed Grafana (AMG) workspaces
#     observability-aws provisions an AMG workspace via Crossplane. Once the hub
#     is gone the Crossplane provider can't reap it (only AMP is covered above),
#     so delete directly. Match by workspace name prefix (e.g. peeks-observability).
# ---------------------------------------------------------------------------
try:
    deleted = 0
    for ws in grafana.list_workspaces().get("workspaces", []):
        if (ws.get("name") or "").startswith(prefix):
            try:
                grafana.delete_workspace(workspaceId=ws["id"])
                log(f"  Deleted AMG workspace {ws['id']} ({ws.get('name')})")
                deleted += 1
            except Exception as e:
                log(f"  AMG workspace {ws['id']}: {e}")
    if deleted == 0:
        log("No AMG workspaces to delete")
except Exception as e:
    log(f"AMG workspaces: {e}")


# ---------------------------------------------------------------------------
# 12. CloudWatch Logs deliveries (EKS capability log delivery)
#     enable-capability-logs creates delivery-source / delivery-destination /
#     delivery IMPERATIVELY (no controller owns them), named <prefix>-*. Section 9
#     only removes log GROUPS, so reap the delivery objects here. Order matters:
#     a delivery-source cannot be deleted while a delivery references it.
# ---------------------------------------------------------------------------
try:
    reaped = 0
    srcs = [
        s["name"]
        for s in logs.describe_delivery_sources().get("deliverySources", [])
        if s["name"].startswith(prefix)
    ]
    for d in logs.describe_deliveries().get("deliveries", []):
        if d.get("deliverySourceName", "") in srcs:
            try:
                logs.delete_delivery(id=d["id"])
                reaped += 1
            except Exception:
                pass
    for name in srcs:
        try:
            logs.delete_delivery_source(name=name)
            reaped += 1
        except Exception as e:
            log(f"  delivery-source {name}: {e}")
    for dd in logs.describe_delivery_destinations().get("deliveryDestinations", []):
        if dd["name"].startswith(prefix):
            try:
                logs.delete_delivery_destination(name=dd["name"])
                reaped += 1
            except Exception:
                pass
    log(f"Reaped {reaped} CloudWatch Logs delivery object(s)" if reaped else "No CW Logs deliveries to delete")
except Exception as e:
    log(f"CW Logs deliveries: {e}")


# ---------------------------------------------------------------------------
# 12b. Elastic Load Balancers provisioned by the AWS Load Balancer Controller
#     ALB/NLB created for in-cluster Ingress/Service are named
#     k8s-<namespace>-<name>-<hash> — they do NOT start with the resource prefix,
#     so section 16b's name filter misses them. When the cluster/nodes are torn
#     down before the controller deletes its LBs, they orphan: they hold
#     ServiceManaged EIPs (which section 13 then skips because the EIP still looks
#     "associated") and RequesterManaged amazon-elb ENIs that block the spoke/IDE
#     VPC reap (sections 10/14). Deleting the LB auto-releases its ServiceManaged
#     EIPs and frees those ENIs, so run this BEFORE the EIP and VPC-reaper sections.
#     Match by the AWS LB Controller ownership tag elbv2.k8s.aws/cluster=<hub|spoke>
#     (catches the k8s-* names) plus the #914 ownership tag and the legacy prefix
#     name. Also reap the matching orphaned target groups.
# ---------------------------------------------------------------------------
try:
    owned_clusters = {hub, *spokes}

    def _lb_owned(arn, name):
        if name.startswith(prefix + "-"):
            return True
        try:
            td = {
                t["Key"]: t["Value"]
                for t in elbv2.describe_tags(ResourceArns=[arn])["TagDescriptions"][0]["Tags"]
            }
        except Exception:
            return False
        return td.get("elbv2.k8s.aws/cluster") in owned_clusters or td.get(OWNER_PREFIX_TAG) == prefix

    reaped_lb = 0
    lbs = []
    for page in elbv2.get_paginator("describe_load_balancers").paginate():
        lbs.extend(page.get("LoadBalancers", []))
    for lb in lbs:
        if not _lb_owned(lb["LoadBalancerArn"], lb["LoadBalancerName"]):
            continue
        try:
            elbv2.delete_load_balancer(LoadBalancerArn=lb["LoadBalancerArn"])
            reaped_lb += 1
            log(f"  Deleted load balancer {lb['LoadBalancerName']}")
        except Exception as e:
            log(f"  LB {lb['LoadBalancerName']}: {e}")

    # Orphaned target groups (LB controller tags them the same way)
    for page in elbv2.get_paginator("describe_target_groups").paginate():
        for tg in page.get("TargetGroups", []):
            if not _lb_owned(tg["TargetGroupArn"], tg["TargetGroupName"]):
                continue
            try:
                elbv2.delete_target_group(TargetGroupArn=tg["TargetGroupArn"])
            except Exception:
                pass

    if reaped_lb:
        log(f"Load balancers: deleted {reaped_lb}")
        time.sleep(20)  # let ServiceManaged EIPs release + amazon-elb ENIs detach
    else:
        log("No orphaned load balancers to delete")
except Exception as e:
    log(f"Load balancers: {e}")


# ---------------------------------------------------------------------------
# 13. Orphaned Elastic IPs
#     Spoke NAT-gateway EIPs (<prefix>-spoke-*-eip*) survive when the NAT is torn
#     down out of order — they persist UNASSOCIATED and keep billing. Release only
#     UNASSOCIATED addresses carrying the workshop prefix in a tag value.
# ---------------------------------------------------------------------------
try:
    released = 0
    for a in ec2.describe_addresses().get("Addresses", []):
        if a.get("AssociationId"):
            continue  # still attached — never touch
        tags = {t["Key"]: t["Value"] for t in a.get("Tags", [])}
        owned = (
            tags.get(OWNER_PREFIX_TAG) == prefix
            or any(prefix in str(v) for v in tags.values())
            or any(prefix in str(k) for k in tags.keys())
        )
        if owned:
            try:
                ec2.release_address(AllocationId=a["AllocationId"])
                log(f"  Released EIP {a.get('PublicIp')} ({tags.get('Name', '-')})")
                released += 1
            except Exception as e:
                log(f"  EIP {a.get('PublicIp')}: {e}")
    if released == 0:
        log("No orphaned EIPs to release")
except Exception as e:
    log(f"Elastic IPs: {e}")


# ---------------------------------------------------------------------------
# 14. Orphan VPC reaper (spoke + Crossplane) — backstop for section 10
#     Section 10 can leave a spoke VPC behind because Auto Mode / KRO ENIs are
#     still detaching right after cluster deletion (delete_vpc fails non-fatally).
#     Also handles Crossplane-provisioned VPCs (tag platform.gitops.io/cluster),
#     which section 10 does not match. Force-clears ENIs and RETRIES delete_vpc.
#     NEVER touches a CFN-owned VPC (aws:cloudformation:* tag) — that is the IDE
#     VPC, which CloudFormation deletes itself.
# ---------------------------------------------------------------------------
try:
    def _reap_vpc(vpc_id):
        for eni in ec2.describe_network_interfaces(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["NetworkInterfaces"]:
            try:
                ec2.delete_network_interface(NetworkInterfaceId=eni["NetworkInterfaceId"])
            except Exception:
                pass
        for nat in ec2.describe_nat_gateways(
            Filter=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("NatGateways", []):
            if nat["State"] not in ("deleted", "deleting"):
                try:
                    ec2.delete_nat_gateway(NatGatewayId=nat["NatGatewayId"])
                except Exception:
                    pass
        for igw in ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )["InternetGateways"]:
            try:
                ec2.detach_internet_gateway(InternetGatewayId=igw["InternetGatewayId"], VpcId=vpc_id)
                ec2.delete_internet_gateway(InternetGatewayId=igw["InternetGatewayId"])
            except Exception:
                pass
        for sn in ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]:
            try:
                ec2.delete_subnet(SubnetId=sn["SubnetId"])
            except Exception:
                pass
        for rt in ec2.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["RouteTables"]:
            if any(a.get("Main", False) for a in rt.get("Associations", [])):
                continue
            for a in rt.get("Associations", []):
                if a.get("RouteTableAssociationId") and not a.get("Main", False):
                    try:
                        ec2.disassociate_route_table(AssociationId=a["RouteTableAssociationId"])
                    except Exception:
                        pass
            try:
                ec2.delete_route_table(RouteTableId=rt["RouteTableId"])
            except Exception:
                pass
        for sg in ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]:
            if sg["GroupName"] == "default":
                continue
            _revoke_sg_rules(sg)
        _delete_vpc_sgs(vpc_id)
        for attempt in range(12):  # retry while ENIs finish detaching (~4 min)
            try:
                ec2.delete_vpc(VpcId=vpc_id)
                log(f"  Deleted orphan VPC {vpc_id}")
                return
            except Exception as e:
                if attempt == 11:
                    log(f"  Orphan VPC {vpc_id}: {e}")
                else:
                    time.sleep(20)

    seen, targets = set(), []
    for flt in (
        {"Name": "tag:eks:kubernetes-resource-name",
         "Values": [f"{prefix}-spoke-dev-vpc", f"{prefix}-spoke-prod-vpc"]},
        {"Name": "tag:Name", "Values": [f"{prefix}-spoke-*-vpc"]},
        {"Name": "tag:platform.gitops.io/cluster", "Values": [hub, f"{prefix}-spoke-*"]},
        # #914: catch any owned VPC by ownership tag, regardless of (arbitrary) name.
        {"Name": f"tag:{OWNER_PREFIX_TAG}", "Values": [prefix]},
    ):
        for v in ec2.describe_vpcs(Filters=[flt]).get("Vpcs", []):
            if v["VpcId"] in seen:
                continue
            if any(t["Key"].startswith("aws:cloudformation:") for t in v.get("Tags", [])):
                continue  # CFN-owned (IDE VPC) — leave it to CloudFormation
            seen.add(v["VpcId"])
            targets.append(v["VpcId"])
    for vpc_id in targets:
        _reap_vpc(vpc_id)
    if not targets:
        log("No orphan spoke/Crossplane VPCs to reap")
except Exception as e:
    log(f"Orphan VPC reaper: {e}")


# ---------------------------------------------------------------------------
# 15. Leftover hub security groups in the IDE (CloudFormation-owned) VPC
#     When the hub cluster shares the IDE VPC, its runtime SGs survive
#     `task destroy`: eks-cluster-sg-<hub>-*, k8s-traffic-*, k8s-platform-*,
#     <prefix>-hub-ingress-http/https, <prefix>-hub-platform-alb-sg,
#     <prefix>-amg-sg, rds-mysql-sg-*. Via circular references they block
#     CloudFormation from deleting the IDE VPC → stack DELETE_FAILED. Delete
#     those SGs (revoke rules first) but LEAVE the VPC itself to CloudFormation
#     (_delete_vpc_sgs skips CFN-owned SGs, so the IDE's own SG is untouched).
# ---------------------------------------------------------------------------
try:
    vpc_id = hub_vpc_id
    if not vpc_id:
        # Fallback: locate the IDE VPC by its Name tag when the hub was already gone.
        for v in ec2.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [f"{prefix}-workshop/IDE-VPC", f"{prefix}-workshop*"]}]
        ).get("Vpcs", []):
            vpc_id = v["VpcId"]
            break
    if vpc_id:
        n = _delete_vpc_sgs(vpc_id)
        log(
            f"Cleared {n} leftover security group(s) in IDE/hub VPC {vpc_id}"
            if n else f"No leftover security groups in IDE/hub VPC {vpc_id}"
        )
    else:
        log("IDE/hub VPC not found — skipping leftover SG cleanup")
except Exception as e:
    log(f"IDE VPC SG cleanup: {e}")


# ---------------------------------------------------------------------------
# 15b. GuardDuty-managed security groups
#     GuardDuty Runtime Monitoring auto-creates a non-CFN security group tagged
#     GuardDutyManaged=true (name GuardDutyManagedSecurityGroup-<vpc>) in every
#     VPC it covers. In the IDE/hub (CloudFormation-owned) VPC it blocks CFN's own
#     delete-vpc → stack DELETE_FAILED; in a spoke VPC it blocks the reaper.
#     _delete_vpc_sgs already removes non-CFN SGs, but GuardDuty can RE-CREATE this
#     one after that pass, so sweep it explicitly here (after the bulk SG clears),
#     scoped to the IDE VPC and every workshop-owned VPC — never unrelated VPCs.
#     Best-effort: if GuardDuty recreates it yet again before CFN's delete-vpc, the
#     delete-stack retain-retry / FORCE_DELETE_STACK reaper is the backstop.
# ---------------------------------------------------------------------------
try:
    _vpc_tags_cache = {}

    def _vpc_is_target(vpc_of_sg):
        if not vpc_of_sg:
            return False
        if vpc_of_sg not in _vpc_tags_cache:
            try:
                vt = ec2.describe_vpcs(VpcIds=[vpc_of_sg])["Vpcs"][0].get("Tags", [])
                _vpc_tags_cache[vpc_of_sg] = {t["Key"]: t["Value"] for t in vt}
            except Exception:
                _vpc_tags_cache[vpc_of_sg] = {}
        vtags = _vpc_tags_cache[vpc_of_sg]
        is_cfn_vpc = any(k.startswith("aws:cloudformation:") for k in vtags.keys())
        is_owned_vpc = (
            vtags.get(OWNER_PREFIX_TAG) == prefix
            or any(prefix in str(v) for v in vtags.values())
        )
        return is_cfn_vpc or is_owned_vpc

    gd_deleted = 0
    for sg in ec2.describe_security_groups(
        Filters=[{"Name": "tag:GuardDutyManaged", "Values": ["true"]}]
    ).get("SecurityGroups", []):
        if not _vpc_is_target(sg.get("VpcId")):
            continue  # only workshop-owned / IDE (CFN) VPCs — never unrelated ones
        _revoke_sg_rules(sg)
        try:
            ec2.delete_security_group(GroupId=sg["GroupId"])
            gd_deleted += 1
            log(f"  Deleted GuardDuty-managed SG {sg['GroupId']} in {sg.get('VpcId')}")
        except Exception as e:
            log(f"  GuardDuty SG {sg['GroupId']}: {e}")
    log(f"GuardDuty SGs: deleted {gd_deleted}" if gd_deleted else "No GuardDuty-managed SGs to delete")
except Exception as e:
    log(f"GuardDuty SGs: {e}")


# ---------------------------------------------------------------------------
# 16. Final authoritative re-sweep of recreatable resources + ENI gate
#     Sections 2-5 delete CloudFront / ALB / RDS / AMP scrapers BEFORE the hub
#     cluster is deleted (section 6). While the hub is still alive its
#     ACK / Crossplane / addon controllers RE-CREATE those resources, which then
#     end up orphaned once the hub is gone — observed on a reused account where
#     `task destroy` did not fully stop the controllers first: the CloudFront
#     "peeks-hub-platform" distribution + VPC origin, the DevLake RDS, the AMP
#     scrapers and the hub security groups all came back and their ENIs
#     (cloudfront_managed / RDSNetworkInterface / amp_collector) blocked the IDE
#     VPC subnet deletion → stack DELETE_FAILED.
#     Now that the hub AND spokes are deleted (sections 6/6b) the controllers are
#     gone, so re-delete anything that came back, re-clear the IDE VPC security
#     groups, then WAIT for those service-managed ENIs to detach so CloudFormation
#     can delete the subnets. Cheap when nothing was recreated (the common case).
# ---------------------------------------------------------------------------
try:
    def _find_ide_vpc():
        """The IDE VPC is the only CloudFormation-owned VPC (aws:cloudformation:*
        tags). Reliable even when the hub cluster was already gone at section 6."""
        if hub_vpc_id:
            return hub_vpc_id
        for v in ec2.describe_vpcs().get("Vpcs", []):
            if any(t["Key"].startswith("aws:cloudformation:") for t in v.get("Tags", [])):
                return v["VpcId"]
        return None

    ide_vpc = _find_ide_vpc()

    # 16a. AMP scrapers (recreated by the AMP capability / addon)
    try:
        for s in amp.list_scrapers().get("scrapers", []):
            try:
                amp.delete_scraper(scraperId=s["scraperId"])
                log(f"  [re-sweep] Deleted recreated AMP scraper {s['scraperId']}")
            except Exception:
                pass
    except Exception as e:
        log(f"  [re-sweep] AMP: {e}")

    # 16b. ALBs (recreated by the AWS Load Balancer Controller). Widened to match
    #      the same way as section 12b — the <prefix>-* name OR the LB-controller
    #      ownership tag elbv2.k8s.aws/cluster=<hub|spoke> (plus the #914 prefix
    #      tag) — so recreated k8s-<ns>-<name>-<hash> LBs are re-swept too, not
    #      only <prefix>-* ones. Reuses the _lb_owned predicate defined in 12b
    #      (module scope), with a self-contained fallback if 12b didn't run.
    try:
        try:
            _resweep_lb_owned = _lb_owned  # defined in section 12b
        except NameError:
            _resweep_owned = {hub, *spokes}

            def _resweep_lb_owned(arn, name):
                if name.startswith(prefix + "-"):
                    return True
                try:
                    td = {
                        t["Key"]: t["Value"]
                        for t in elbv2.describe_tags(
                            ResourceArns=[arn]
                        )["TagDescriptions"][0]["Tags"]
                    }
                except Exception:
                    return False
                return (
                    td.get("elbv2.k8s.aws/cluster") in _resweep_owned
                    or td.get(OWNER_PREFIX_TAG) == prefix
                )

        for lb in elbv2.describe_load_balancers()["LoadBalancers"]:
            if _resweep_lb_owned(lb["LoadBalancerArn"], lb["LoadBalancerName"]):
                elbv2.delete_load_balancer(LoadBalancerArn=lb["LoadBalancerArn"])
                log(f"  [re-sweep] Deleted recreated ALB {lb['LoadBalancerName']}")
    except Exception as e:
        log(f"  [re-sweep] ALB: {e}")

    # 16c. RDS (recreated by ACK)
    try:
        for db in rds.describe_db_instances()["DBInstances"]:
            if db["DBInstanceIdentifier"].startswith("devlake") \
               and db["DBInstanceStatus"] not in ("deleting",):
                rds.delete_db_instance(
                    DBInstanceIdentifier=db["DBInstanceIdentifier"],
                    SkipFinalSnapshot=True,
                    DeleteAutomatedBackups=True,
                )
                log(f"  [re-sweep] Deleting recreated RDS {db['DBInstanceIdentifier']}")
    except Exception as e:
        log(f"  [re-sweep] RDS: {e}")

    # 16d. CloudFront distribution + VPC origin (recreated by Crossplane)
    try:
        vos = cf.list_vpc_origins().get("VpcOriginList", {}).get("Items", [])
        vo_ids = {vo["Id"] for vo in vos if vo.get("Name", "").startswith(hub + "-")}
        dist_ids = set()
        for d in cf.list_distributions().get("DistributionList", {}).get("Items", []):
            if d.get("Comment", "").startswith(hub):
                dist_ids.add(d["Id"])
                continue
            for o in d.get("Origins", {}).get("Items", []):
                if o.get("VpcOriginConfig", {}).get("VpcOriginId", "") in vo_ids:
                    dist_ids.add(d["Id"])
        for dist_id in dist_ids:
            resp = cf.get_distribution_config(Id=dist_id)
            etag, cfg = resp["ETag"], resp["DistributionConfig"]
            if cfg.get("Enabled", True):
                cfg["Enabled"] = False
                cf.update_distribution(Id=dist_id, DistributionConfig=cfg, IfMatch=etag)
                log(f"  [re-sweep] Disabling recreated CF distribution {dist_id}...")
                for _ in range(30):
                    if cf.get_distribution(Id=dist_id)["Distribution"]["Status"] == "Deployed":
                        break
                    time.sleep(15)
            etag2 = cf.get_distribution(Id=dist_id)["ETag"]
            cf.delete_distribution(Id=dist_id, IfMatch=etag2)
            log(f"  [re-sweep] Deleted recreated CF distribution {dist_id}")
        if dist_ids:
            time.sleep(5)
        for vo_id in vo_ids:
            try:
                etag = cf.get_vpc_origin(Id=vo_id)["ETag"]
                cf.delete_vpc_origin(Id=vo_id, IfMatch=etag)
                log(f"  [re-sweep] Deleted recreated CF VPC origin {vo_id}")
            except Exception:
                pass
    except Exception as e:
        log(f"  [re-sweep] CloudFront: {e}")

    # 16e. Re-clear leftover SGs in the IDE VPC (recreated / missed by section 15)
    if ide_vpc:
        n = _delete_vpc_sgs(ide_vpc)
        if n:
            log(f"  [re-sweep] Cleared {n} more leftover SG(s) in IDE VPC {ide_vpc}")

    # 16f. ENI gate — wait for the service-managed ENIs that block subnet deletion
    #      (cloudfront_managed / amp_collector / RDSNetworkInterface) to detach.
    if ide_vpc:
        def _blocking_enis():
            out = []
            try:
                for e in ec2.describe_network_interfaces(
                    Filters=[{"Name": "vpc-id", "Values": [ide_vpc]}]
                )["NetworkInterfaces"]:
                    if e.get("InterfaceType") in ("amp_collector", "cloudfront_managed") \
                       or e.get("Description", "").startswith("RDSNetworkInterface"):
                        out.append(e["NetworkInterfaceId"])
            except Exception:
                pass
            return out
        for i in range(36):  # up to ~12 min (36 × 20 s) — RDS ENI release is the long pole
            b = _blocking_enis()
            if not b:
                log(f"  [re-sweep] No blocking ENIs left in IDE VPC {ide_vpc}")
                break
            if i % 3 == 0:
                log(f"  [re-sweep] Waiting for {len(b)} blocking ENI(s) to detach from IDE VPC {ide_vpc}...")
            time.sleep(20)
    else:
        log("  [re-sweep] IDE VPC not found — skipping final re-sweep")
except Exception as e:
    log(f"Final re-sweep: {e}")


log("Extended sweep complete.")
