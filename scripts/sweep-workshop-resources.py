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


def log(msg):
    print(f"[sweep] {msg}", flush=True)


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
    cluster_status = eks.describe_cluster(name=hub)["cluster"]["status"]
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
# 7. IAM roles + customer-managed policies
#    task destroy removes most IAM resources via Terraform, but some roles
#    created directly (peeks-cluster-mgmt-*, peeks-hub-cluster-*) may remain.
#    Skip team-stack and SharedRole resources owned by CFN itself.
# ---------------------------------------------------------------------------
try:
    _skip = ("-team-stack-", "SharedRole")
    count = 0
    for role in sum(
        [p["Roles"] for p in iam.get_paginator("list_roles").paginate()], []
    ):
        n = role["RoleName"]
        if not n.startswith(prefix + "-") or any(x in n for x in _skip):
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

    for pol in iam.list_policies(Scope="Local")["Policies"]:
        n = pol["PolicyName"]
        if not n.startswith(prefix + "-") or any(x in n for x in _skip):
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
    for s in sm.list_secrets(Filters=[{"Key": "name", "Values": [prefix]}])["SecretList"]:
        try:
            sm.delete_secret(SecretId=s["ARN"], ForceDeleteWithoutRecovery=True)
        except Exception:
            pass
except Exception as e:
    log(f"Secrets Manager: {e}")


# ---------------------------------------------------------------------------
# 9. CloudWatch Log Groups
#    EKS control-plane log groups survive cluster deletion and should be removed.
# ---------------------------------------------------------------------------
try:
    for pfx in [
        f"/aws/eks/{prefix}-hub",
        f"/aws/eks/{prefix}-spoke-dev",
        f"/aws/eks/{prefix}-spoke-prod",
    ]:
        for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=pfx):
            for lg in page["logGroups"]:
                try:
                    logs.delete_log_group(logGroupName=lg["logGroupName"])
                except Exception:
                    pass
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
        # Security Groups (non-default)
        for sg in ec2.describe_security_groups(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["SecurityGroups"]:
            if sg["GroupName"] == "default":
                continue
            try:
                ec2.delete_security_group(GroupId=sg["GroupId"])
            except Exception:
                pass
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


log("Extended sweep complete.")
