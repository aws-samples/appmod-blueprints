#!/usr/bin/env python3
"""
sweep-spoke-vpcs.py RESOURCE_PREFIX AWS_REGION
Deletes orphaned spoke VPCs tagged with eks:kubernetes-resource-name=<prefix>-spoke-*-vpc.
Called by task kind-kro-ack:destroy step 6h.
"""
import boto3, sys, time

prefix = sys.argv[1] if len(sys.argv) > 1 else 'peeks'
region = sys.argv[2] if len(sys.argv) > 2 else 'us-west-2'
ec2 = boto3.client('ec2', region_name=region)

spoke_vpcs = []
try:
    resp = ec2.describe_vpcs(Filters=[{
        'Name': 'tag:eks:kubernetes-resource-name',
        'Values': [f'{prefix}-spoke-dev-vpc', f'{prefix}-spoke-prod-vpc']
    }])
    spoke_vpcs = [v['VpcId'] for v in resp['Vpcs']]
except Exception as e:
    print(f'  describe-vpcs error: {e}', file=sys.stderr)

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
