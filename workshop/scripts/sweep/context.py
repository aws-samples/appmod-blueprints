"""Shared state + helpers for the teardown sweep (issue #924, principle #2).

`SweepContext` holds the boto3 clients, the resolved region/prefix/hub/spokes,
the mutable `hub_vpc_id` (discovered in the EKS reaper, read by the VPC and
re-sweep reapers), and the VPC-ownership / security-group helpers shared across
reapers. Splitting the former 1400-line procedural script into per-service
reaper modules that all receive this context is what shrinks the entrypoint and
makes each concern independently reviewable/testable.

SAFETY (VPC ownership): a CloudFormation tag does NOT imply this workshop owns a
VPC — every CDK stack carries aws:cloudformation:* tags. Ownership is POSITIVE
identification only (prefix tag / cluster tag / Name prefix / this stack's IDE
VPC). This preserves the exact behavior of the pre-split script.
"""

from __future__ import annotations

import boto3

# PR #914 stamps every workshop-owned EKS cluster and VPC with this ownership tag,
# so arbitrarily-named spokes (e.g. "oap-test") are still discovered/reaped.
OWNER_PREFIX_TAG = "platform.gitops.io/prefix"


def _log(msg):
    print(f"[sweep] {msg}", flush=True)


class SweepContext:
    """Boto3 clients + resolved identifiers + shared helpers, passed to every reaper."""

    def __init__(self, region, prefix):
        self.region = region
        self.prefix = prefix
        self.hub = f"{prefix}-hub"
        self.OWNER_PREFIX_TAG = OWNER_PREFIX_TAG

        self.eks = boto3.client("eks", region_name=region)
        self.iam = boto3.client("iam")
        self.ec2 = boto3.client("ec2", region_name=region)
        self.elbv2 = boto3.client("elbv2", region_name=region)
        self.rds = boto3.client("rds", region_name=region)
        self.amp = boto3.client("amp", region_name=region)
        self.sm = boto3.client("secretsmanager", region_name=region)
        self.logs = boto3.client("logs", region_name=region)
        self.cf = boto3.client("cloudfront")
        self.grafana = boto3.client("grafana", region_name=region)
        self.ecr = boto3.client("ecr", region_name=region)
        self.s3 = boto3.client("s3")

        # Mutable shared state: set by the hub EKS reaper (§6), read by the VPC
        # SG reaper (§15) and the final re-sweep (§16).
        self.hub_vpc_id = None

        self._vpc_tag_cache = {}
        self.spokes = self.discover_spokes()

    # ── logging ────────────────────────────────────────────────────────────────
    def log(self, msg):
        _log(msg)

    # ── spoke discovery ──────────────────────────────────────────────────────────
    def discover_spokes(self):
        """Union of the legacy spoke name pattern and every non-hub EKS cluster
        carrying platform.gitops.io/prefix=<prefix> (#914 ownership tag)."""
        eks, hub, prefix = self.eks, self.hub, self.prefix
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
                        self.log(f"  Discovered owned spoke by tag: {name}")
        except Exception as e:
            self.log(f"Spoke discovery: {e}")
        return sorted(found)

    # ── VPC ownership (positive identification only) ─────────────────────────────
    def _vpc_tags(self, vpc_id):
        if vpc_id not in self._vpc_tag_cache:
            try:
                v = self.ec2.describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]
                self._vpc_tag_cache[vpc_id] = {t["Key"]: t["Value"] for t in v.get("Tags", [])}
            except Exception:
                self._vpc_tag_cache[vpc_id] = {}
        return self._vpc_tag_cache[vpc_id]

    def is_our_ide_vpc(self, tags):
        """The IDE VPC belongs to THIS workshop's CloudFormation stack. Requires the
        stack name to reference this deployment — never just 'any CFN stack'."""
        stack = tags.get("aws:cloudformation:stack-name", "")
        if not stack:
            return False
        return self.prefix in stack or "peeks" in stack.lower() or "workshop" in stack.lower()

    def vpc_is_ours(self, vpc_id):
        if not vpc_id:
            return False
        tags = self._vpc_tags(vpc_id)
        if tags.get(OWNER_PREFIX_TAG) == self.prefix:
            return True
        if tags.get("platform.gitops.io/cluster") in {self.hub, *self.spokes}:
            return True
        if tags.get("Name", "").startswith(self.prefix + "-"):
            return True
        return self.is_our_ide_vpc(tags)

    # ── security-group helpers ───────────────────────────────────────────────────
    def revoke_sg_rules(self, sg):
        """Revoke a security group's ingress/egress rules so circular SG references
        (e.g. eks-cluster-sg <-> k8s-traffic-*) don't block deletion."""
        gid = sg["GroupId"]
        if sg.get("IpPermissions"):
            try:
                self.ec2.revoke_security_group_ingress(GroupId=gid, IpPermissions=sg["IpPermissions"])
            except Exception:
                pass
        if sg.get("IpPermissionsEgress"):
            try:
                self.ec2.revoke_security_group_egress(GroupId=gid, IpPermissions=sg["IpPermissionsEgress"])
            except Exception:
                pass

    def delete_vpc_sgs(self, vpc_id):
        """Delete every non-default, non-CloudFormation-owned security group in a VPC.
        Two passes (revoke all rules, then delete all) to survive circular references.
        Leaves CFN-owned SGs (aws:cloudformation:* tag) and the VPC itself untouched.
        Returns the number of SGs deleted."""
        try:
            sgs = [
                s for s in self.ec2.describe_security_groups(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )["SecurityGroups"]
                if s["GroupName"] != "default"
                and not any(t["Key"].startswith("aws:cloudformation:") for t in s.get("Tags", []))
            ]
        except Exception:
            return 0
        for s in sgs:
            self.revoke_sg_rules(s)
        deleted = 0
        for s in sgs:
            try:
                self.ec2.delete_security_group(GroupId=s["GroupId"])
                deleted += 1
            except Exception:
                pass
        return deleted
