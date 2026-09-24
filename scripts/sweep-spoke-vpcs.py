#!/usr/bin/env python3
"""
sweep-spoke-vpcs.py RESOURCE_PREFIX AWS_REGION [HUB_CLUSTER_NAME]
Deletes orphaned spoke VPCs left behind after the spoke clusters are gone.
Called by task kind-kro-ack:destroy step 6h.

Selects by OWNERSHIP TAG, not by name. Spoke names are arbitrary, so the previous
filter — the two literal values <prefix>-spoke-dev-vpc and <prefix>-spoke-prod-vpc —
could not see a spoke called anything else (including a conforming third one such as
<prefix>-spoke-staging). Destroy reported success while leaving that spoke's VPC, NAT
gateway, EIP, subnets and route tables behind, and the orphaned route tables then
blocked the VPC deletion.

The legacy names are still included, so a pre-tag install sweeps exactly what it
swept before.

HUB_CLUSTER_NAME is optional but should be passed: the hub is provisioned through the
same resource graphs and carries the same ownership tag, so without it a tag-based
sweep would pull the hub's VPC into a spoke sweep. It cannot be derived as
<prefix>-hub, because cluster names are arbitrary.
"""
import boto3, sys, time

prefix = sys.argv[1] if len(sys.argv) > 1 else 'peeks'
region = sys.argv[2] if len(sys.argv) > 2 else 'us-west-2'
hub = sys.argv[3] if len(sys.argv) > 3 else ''
ec2 = boto3.client('ec2', region_name=region)


def _tag(vpc, key):
    return next((t['Value'] for t in vpc.get('Tags', []) if t['Key'] == key), '')


def _discover():
    found = {}
    for desc, filters in (
        ('legacy name', [{'Name': 'tag:eks:kubernetes-resource-name',
                          'Values': [f'{prefix}-spoke-dev-vpc', f'{prefix}-spoke-prod-vpc']}]),
        ('ownership tag', [{'Name': 'tag:platform.gitops.io/prefix', 'Values': [prefix]}]),
    ):
        try:
            for v in ec2.describe_vpcs(Filters=filters)['Vpcs']:
                found[v['VpcId']] = v
        except Exception as e:
            print(f'  describe-vpcs ({desc}): {e}', file=sys.stderr)

    out = []
    for vpc_id, v in found.items():
        # Never sweep the hub here — this script handles spokes only; the hub has its
        # own teardown path earlier in destroy.
        if hub and (_tag(v, 'platform.gitops.io/cluster') == hub
                    or _tag(v, 'Name') == f'{hub}-vpc'):
            print(f'  Skipping hub VPC {vpc_id} ({hub})')
            continue
        out.append(vpc_id)
    return sorted(out)


spoke_vpcs = _discover()

if not spoke_vpcs:
    print('  No orphaned spoke VPCs found.')
    sys.exit(0)

for vpc_id in spoke_vpcs:
    print(f'  Cleaning spoke VPC {vpc_id}...')

    nat_eips = []
    try:
        nats = ec2.describe_nat_gateways(Filters=[
            {'Name': 'vpc-id', 'Values': [vpc_id]},
            {'Name': 'state', 'Values': ['available', 'pending']}
        ])['NatGateways']
        for nat in nats:
            for addr in nat.get('NatGatewayAddresses', []):
                if addr.get('AllocationId'):
                    nat_eips.append(addr['AllocationId'])
            try:
                ec2.delete_nat_gateway(NatGatewayId=nat['NatGatewayId'])
                print(f'    started NAT GW deletion')
            except: pass
    except: pass

    try:
        igws = ec2.describe_internet_gateways(
            Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
        )['InternetGateways']
        for igw in igws:
            try:
                ec2.detach_internet_gateway(InternetGatewayId=igw['InternetGatewayId'], VpcId=vpc_id)
                ec2.delete_internet_gateway(InternetGatewayId=igw['InternetGatewayId'])
                print(f'    ✓ deleted IGW')
            except: pass
    except: pass

    try:
        subnets = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['Subnets']
        for sn in subnets:
            try: ec2.delete_subnet(SubnetId=sn['SubnetId'])
            except: pass
    except: pass

    try:
        rts = ec2.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['RouteTables']
        for rt in rts:
            if any(a.get('Main', False) for a in rt.get('Associations', [])):
                continue
            for a in rt.get('Associations', []):
                if not a.get('Main', False) and a.get('RouteTableAssociationId'):
                    try: ec2.disassociate_route_table(AssociationId=a['RouteTableAssociationId'])
                    except: pass
            try: ec2.delete_route_table(RouteTableId=rt['RouteTableId'])
            except: pass
    except: pass

    try:
        sgs = ec2.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['SecurityGroups']
        for sg in sgs:
            if sg['GroupName'] == 'default':
                continue
            if sg.get('IpPermissions'):
                try: ec2.revoke_security_group_ingress(GroupId=sg['GroupId'], IpPermissions=sg['IpPermissions'])
                except: pass
            if sg.get('IpPermissionsEgress'):
                try: ec2.revoke_security_group_egress(GroupId=sg['GroupId'], IpPermissions=sg['IpPermissionsEgress'])
                except: pass
            try: ec2.delete_security_group(GroupId=sg['GroupId'])
            except: pass
    except: pass

    if nat_eips:
        time.sleep(30)
        for alloc_id in nat_eips:
            try: ec2.release_address(AllocationId=alloc_id)
            except: pass

    # Wait for any lingering async ENIs to clear before attempting VPC delete.
    # AMP scrapers (amp_collector ENIs) take 3-5 min to release after deletion.
    # NAT GW ENIs also clear asynchronously after the 30s wait above.
    for attempt in range(12):  # up to ~2 min of additional waiting
        enis = ec2.describe_network_interfaces(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['NetworkInterfaces']
        if not enis:
            break
        # Only async-cleanup ENIs? Keep waiting. Other ENIs = real blocking dependency.
        async_types = {'amp_collector', 'natGateway'}
        blocking = [e for e in enis if e.get('InterfaceType', '') not in async_types]
        if blocking:
            for e in blocking:
                print(f'    ⚠ blocking ENI: {e["NetworkInterfaceId"]} '
                      f'{e.get("InterfaceType","")} {e.get("Description","")[:50]}')
            break  # Non-async ENI found — stop waiting, delete_vpc will fail with detail
        print(f'    Waiting for {len(enis)} async ENI(s) to clear '
              f'(attempt {attempt+1}/12)...')
        time.sleep(10)

    try:
        ec2.delete_vpc(VpcId=vpc_id)
        print(f'  ✓ deleted spoke VPC {vpc_id}')
    except Exception as e:
        print(f'  ⚠ spoke VPC {vpc_id}: {e}')
