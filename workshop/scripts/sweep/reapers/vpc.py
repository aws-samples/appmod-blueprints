"""VPC / network reapers: spoke VPCs (§10), GuardDuty VPC endpoints (§13b),
orphan VPC reaper (§14), IDE-VPC leftover SGs (§15), GuardDuty SGs (§15b)."""

import time

from ..resilience import poll_until, retry_aws


def reap_spoke_vpcs(ctx):
    """§10. ACK/Crossplane spoke VPCs (tag eks:kubernetes-resource-name), not part
    of the IDE CFN stack — deleted separately."""
    log, ec2, prefix = ctx.log, ctx.ec2, ctx.prefix
    _delete_vpc_sgs = ctx.delete_vpc_sgs
    try:
        spoke_vpcs = ec2.describe_vpcs(
            Filters=[
                {
                    "Name": "tag:eks:kubernetes-resource-name",
                    "Values": [f"{prefix}-spoke-dev-vpc", f"{prefix}-spoke-prod-vpc"],
                }
            ]
        )["Vpcs"]

        for v in spoke_vpcs:
            vpc_id = v["VpcId"]
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
                    if not a.get("Main", False) and a.get("RouteTableAssociationId"):
                        try:
                            ec2.disassociate_route_table(AssociationId=a["RouteTableAssociationId"])
                        except Exception:
                            pass
                try:
                    ec2.delete_route_table(RouteTableId=rt["RouteTableId"])
                except Exception:
                    pass
            _delete_vpc_sgs(vpc_id)
            try:
                ec2.delete_vpc(VpcId=vpc_id)
                log(f"  Deleted spoke VPC {vpc_id}")
            except Exception as e:
                log(f"  Spoke VPC {vpc_id}: {e}")

        if not spoke_vpcs:
            log("No spoke VPCs to delete")
    except Exception as e:
        log(f"Spoke VPCs: {e}")


def reap_guardduty_endpoints(ctx):
    """§13b. GuardDuty Runtime Monitoring auto-creates a guardduty-data interface VPC
    endpoint whose ENIs block subnet/VPC deletion. Delete FIRST, scoped to owned VPCs."""
    log, ec2 = ctx.log, ctx.ec2
    _vpc_is_ours = ctx.vpc_is_ours
    try:
        gd_eps = []
        for ep in ec2.describe_vpc_endpoints().get("VpcEndpoints", []):
            if "guardduty-data" not in ep.get("ServiceName", ""):
                continue
            if not _vpc_is_ours(ep.get("VpcId")):
                continue  # only VPCs this workshop created / its own IDE VPC
            gd_eps.append(ep["VpcEndpointId"])
        if gd_eps:
            ec2.delete_vpc_endpoints(VpcEndpointIds=gd_eps)
            log(f"  Deleted {len(gd_eps)} guardduty-data VPC endpoint(s): {', '.join(gd_eps)}")
            time.sleep(30)  # let the endpoint ENIs detach before subnet/VPC deletion
        else:
            log("No guardduty-data VPC endpoints to delete")
    except Exception as e:
        log(f"GuardDuty VPC endpoints: {e}")


def reap_orphan_vpcs(ctx):
    """§14. Backstop for §10: force-clears ENIs and RE-DRIVES delete_vpc for spoke +
    Crossplane VPCs. NEVER touches a CFN-owned VPC (that is the IDE VPC)."""
    log, ec2, prefix, hub = ctx.log, ctx.ec2, ctx.prefix, ctx.hub
    OWNER_PREFIX_TAG = ctx.OWNER_PREFIX_TAG
    _revoke_sg_rules, _delete_vpc_sgs = ctx.revoke_sg_rules, ctx.delete_vpc_sgs
    try:
        def _clear_vpc_deps(vpc_id):
            """One pass of dependency clearing. Safe to call repeatedly — subnet and
            VPC deletion only succeed once NAT gateways finish deleting and release
            their service-managed ENIs, so _reap_vpc re-drives this each retry."""
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

        def _reap_vpc(vpc_id):
            """Delete a VPC, re-driving the full dependency clear on EVERY attempt.
            poll_until drives the ~6 min re-drive cadence; retry_aws absorbs the
            transient DependencyViolation within an attempt and treats an
            already-gone VPC as success. Returns True on deletion."""
            _rv = {"deleted": False, "last": None}

            def _try_reap():
                _clear_vpc_deps(vpc_id)
                try:
                    retry_aws(ec2.delete_vpc, VpcId=vpc_id, attempts=1)
                    log(f"  Deleted orphan VPC {vpc_id}")
                    _rv["deleted"] = True
                    return True
                except Exception as e:
                    _rv["last"] = e
                    return False

            if not poll_until(_try_reap, attempts=18, delay=20):
                log(f"  Orphan VPC {vpc_id}: still blocked after ~6 min — {_rv['last']}")
            return _rv["deleted"]

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


def reap_ide_sgs(ctx):
    """§15. Leftover hub SGs in the IDE (CFN-owned) VPC block CFN's delete-vpc via
    circular refs. Delete those SGs but LEAVE the VPC to CloudFormation."""
    log, ec2, prefix = ctx.log, ctx.ec2, ctx.prefix
    _delete_vpc_sgs = ctx.delete_vpc_sgs
    try:
        vpc_id = ctx.hub_vpc_id
        if not vpc_id:
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


def reap_guardduty_sgs(ctx):
    """§15b. GuardDuty auto-creates a non-CFN SG (GuardDutyManaged=true) that blocks
    delete-vpc. _delete_vpc_sgs already removes non-CFN SGs, but GuardDuty can
    RE-CREATE this one, so sweep it explicitly, scoped to owned VPCs only."""
    log, ec2 = ctx.log, ctx.ec2
    _vpc_is_ours, _revoke_sg_rules = ctx.vpc_is_ours, ctx.revoke_sg_rules
    try:
        gd_deleted = 0
        for sg in ec2.describe_security_groups(
            Filters=[{"Name": "tag:GuardDutyManaged", "Values": ["true"]}]
        ).get("SecurityGroups", []):
            if not _vpc_is_ours(sg.get("VpcId")):
                continue  # only VPCs this workshop created / its own IDE VPC.
                # NOTE: _revoke_sg_rules below strips rules BEFORE the delete, and the
                # revoke is not blocked even when AWS refuses the delete. So this guard
                # must be correct: a false positive mutates a live security group.
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
