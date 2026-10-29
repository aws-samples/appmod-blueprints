"""Shared selection and cleanup logic for the kind-kro-ack teardown sweep.

Used by sweep-spoke-vpcs.py, sweep-hub-vpc.py, sweep-rds.py, sweep-log-groups.py
and sweep-iam-guard.py (task kind-kro-ack:destroy, step 6). Every selector is
scoped to one resource prefix and returns what it SKIPPED and why, so a dry run
can show both sides.

Safety rules shared by every sweep:
  * Never touch a CloudFormation-owned VPC (the IDE/hub VPC of the workshop
    template). CloudFormation deletes it with the stack.
  * Never touch a VPC that still hosts an EKS cluster which is not DELETING.
    A cluster kept by deletionPolicy=retain (for example a spoke the hub is
    asked to leave behind) stays ACTIVE, and deleting its VPC's NAT gateway or
    route tables would cut it off.
  * Never touch a VPC whose platform.gitops.io/prefix tag is not exactly the
    prefix being destroyed, nor one tagged for a cluster the inventory marks as
    retained.
  * Never delete an IAM role that a live EKS cluster still references (cluster
    role, access entry, capability role, pod identity association).

The "inventory" is a JSON file written by destroy BEFORE the hub is torn down,
while the hub API and kro instances can still be read:
  {"hub_vpc_id": "vpc-...", "clusters": [{"name": "...", "deletionPolicy": "delete"}]}
It is optional: every sweep falls back to AWS tags when it is missing.

"assume_deleted" exists only for --dry-run: it lets an operator preview a
teardown on a live environment by treating the named clusters as already gone.
"""
import json
import re
import sys
import time

PREFIX_TAG = 'platform.gitops.io/prefix'
CLUSTER_TAG = 'platform.gitops.io/cluster'
LIVE = 'live'


def log(msg):
    print(msg, flush=True)


def tag(obj, key):
    return next((t['Value'] for t in (obj.get('Tags') or []) if t['Key'] == key), '')


def load_inventory(path):
    """Return {'hub_vpc_id': str, 'clusters': [...]} or an empty inventory."""
    empty = {'hub_vpc_id': '', 'clusters': []}
    if not path:
        return empty
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log(f'  inventory {path} not readable ({e}); falling back to AWS tags')
        return empty
    data.setdefault('hub_vpc_id', '')
    data.setdefault('clusters', [])
    return data


def retained_clusters(inventory):
    return {c['name'] for c in inventory.get('clusters', [])
            if (c.get('deletionPolicy') or '').lower() == 'retain' and c.get('name')}


def deleted_clusters(inventory):
    return {c['name'] for c in inventory.get('clusters', [])
            if (c.get('deletionPolicy') or 'delete').lower() != 'retain' and c.get('name')}


def is_cfn_owned(vpc):
    return (any(t['Key'].startswith('aws:cloudformation:') for t in (vpc.get('Tags') or []))
            or tag(vpc, 'ResourceType') == 'ideHubVPC')


# ---------------------------------------------------------------- EKS clusters

def cluster_inventory(eks):
    """All EKS clusters in the region: name -> {status, vpc, roleArn, tags}."""
    out = {}
    names = []
    token = None
    while True:
        resp = eks.list_clusters(**({'nextToken': token} if token else {}))
        names += resp.get('clusters', [])
        token = resp.get('nextToken')
        if not token:
            break
    for name in names:
        try:
            c = eks.describe_cluster(name=name)['cluster']
        except Exception as e:  # cluster vanished between list and describe
            if 'ResourceNotFound' in str(e):
                continue
            raise
        out[name] = {
            'status': c.get('status', ''),
            'vpc': (c.get('resourcesVpcConfig') or {}).get('vpcId', ''),
            'roleArn': c.get('roleArn', ''),
            'tags': c.get('tags') or {},
        }
    return out


def live_clusters(clusters, assume_deleted=()):
    """Clusters that still exist and are not being deleted."""
    return {n: c for n, c in clusters.items()
            if c['status'] != 'DELETING' and n not in set(assume_deleted)}


def busy_vpcs(clusters, assume_deleted=()):
    """VPC id -> names of live clusters running in it."""
    out = {}
    for n, c in live_clusters(clusters, assume_deleted).items():
        if c['vpc']:
            out.setdefault(c['vpc'], []).append(n)
    return out


def _vpc_guard(vpc, prefix, busy, retained):
    """Return a skip reason, or '' when the VPC may be swept."""
    vpc_id = vpc['VpcId']
    if is_cfn_owned(vpc):
        return 'CloudFormation-owned VPC (IDE/hub VPC; the stack deletes it)'
    owner = tag(vpc, PREFIX_TAG)
    if owner and owner != prefix:
        return f'prefix tag is {owner!r}, not {prefix!r}'
    if vpc_id in busy:
        return f'hosts live EKS cluster(s) {", ".join(sorted(busy[vpc_id]))}'
    cl = tag(vpc, CLUSTER_TAG)
    if cl and cl in retained:
        return f'cluster {cl} is kept by deletionPolicy=retain'
    return ''


# ---------------------------------------------------------------- VPC selection

def select_spoke_vpcs(ec2, prefix, hub, clusters, inventory=None, assume_deleted=()):
    """(selected_ids, [(vpc_id, reason)]) for orphaned spoke VPCs of `prefix`."""
    inventory = inventory or {'clusters': []}
    found = {}
    legacy = [f'{prefix}-spoke-dev-vpc', f'{prefix}-spoke-prod-vpc']
    for desc, filters in (
        ('legacy name', [{'Name': 'tag:eks:kubernetes-resource-name', 'Values': legacy}]),
        ('ownership tag', [{'Name': f'tag:{PREFIX_TAG}', 'Values': [prefix]}]),
    ):
        try:
            for v in ec2.describe_vpcs(Filters=filters)['Vpcs']:
                found[v['VpcId']] = v
        except Exception as e:
            log(f'  describe-vpcs ({desc}): {e}')
    busy = busy_vpcs(clusters, assume_deleted)
    retained = retained_clusters(inventory)
    selected, skipped = [], []
    for vpc_id, v in sorted(found.items()):
        reason = _vpc_guard(v, prefix, busy, retained)
        if not reason and hub and (tag(v, CLUSTER_TAG) == hub or tag(v, 'Name') == f'{hub}-vpc'):
            reason = f'hub VPC ({hub}): swept by sweep-hub-vpc.py once the hub is gone'
        if not reason and not tag(v, CLUSTER_TAG) and \
                tag(v, 'eks:kubernetes-resource-name') not in legacy:
            reason = f'no {CLUSTER_TAG} tag'
        if reason:
            skipped.append((vpc_id, reason))
        else:
            selected.append(vpc_id)
    return selected, skipped


def select_hub_vpc(ec2, prefix, hub, clusters, inventory=None, assume_deleted=()):
    """(selected_ids, [(vpc_id, reason)]) for the hub's own VPC.

    The hub EksclusterWithVpc is born with deletionPolicy=retain on kind, and
    destroy deletes the hub cluster through the AWS API, so nothing deletes the
    VPC kro/ACK created for it. Candidates: the VPC id destroy recorded before
    deleting the hub, plus any VPC tagged prefix=<prefix> and cluster=<hub>.
    """
    inventory = inventory or {'clusters': []}
    found = {}
    hint = inventory.get('hub_vpc_id') or ''
    if hint:
        try:
            for v in ec2.describe_vpcs(VpcIds=[hint])['Vpcs']:
                found[v['VpcId']] = v
        except Exception as e:
            if 'NotFound' not in str(e):
                log(f'  describe-vpcs {hint}: {e}')
    if hub:
        try:
            for v in ec2.describe_vpcs(Filters=[
                    {'Name': f'tag:{PREFIX_TAG}', 'Values': [prefix]},
                    {'Name': f'tag:{CLUSTER_TAG}', 'Values': [hub]}])['Vpcs']:
                found[v['VpcId']] = v
        except Exception as e:
            log(f'  describe-vpcs (hub tags): {e}')
    busy = busy_vpcs(clusters, assume_deleted)
    retained = retained_clusters(inventory)
    selected, skipped = [], []
    for vpc_id, v in sorted(found.items()):
        reason = _vpc_guard(v, prefix, busy, retained)
        if not reason and tag(v, PREFIX_TAG) != prefix:
            reason = f'no {PREFIX_TAG}={prefix} tag (not provably ours)'
        if not reason and tag(v, CLUSTER_TAG) != hub and tag(v, 'Name') != f'{hub}-vpc':
            reason = f'not tagged for hub {hub}'
        if reason:
            skipped.append((vpc_id, reason))
        else:
            selected.append(vpc_id)
    return selected, skipped


# ---------------------------------------------------------------- VPC cleanup

ASYNC_ENI_TYPES = {'amp_collector', 'natGateway', 'vpc_endpoint'}


def _ids(items, key):
    return [i[key] for i in items]


def vpc_contents(ec2, vpc_id):
    f = [{'Name': 'vpc-id', 'Values': [vpc_id]}]
    nats = ec2.describe_nat_gateways(Filters=f + [
        {'Name': 'state', 'Values': ['available', 'pending', 'failed']}])['NatGateways']
    return {
        'nat': nats,
        'eip': [a['AllocationId'] for n in nats for a in n.get('NatGatewayAddresses', [])
                if a.get('AllocationId')],
        'endpoint': [e for e in ec2.describe_vpc_endpoints(Filters=f)['VpcEndpoints']
                     if e.get('State', '').lower() not in ('deleted', 'deleting')],
        'igw': ec2.describe_internet_gateways(
            Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}])['InternetGateways'],
        'subnet': ec2.describe_subnets(Filters=f)['Subnets'],
        'rt': [r for r in ec2.describe_route_tables(Filters=f)['RouteTables']
               if not any(a.get('Main') for a in r.get('Associations', []))],
        'sg': [s for s in ec2.describe_security_groups(Filters=f)['SecurityGroups']
               if s['GroupName'] != 'default'],
    }


def describe_plan(ec2, vpc_id):
    c = vpc_contents(ec2, vpc_id)
    return (f'{len(c["nat"])} NAT, {len(c["eip"])} NAT EIP, {len(c["endpoint"])} endpoint, '
            f'{len(c["igw"])} IGW, {len(c["subnet"])} subnet, {len(c["rt"])} route table, '
            f'{len(c["sg"])} SG')


def err_code(e):
    """The AWS error code only: the full message carries ARNs and principals."""
    code = (getattr(e, 'response', None) or {}).get('Error', {}).get('Code')
    if code:
        return code
    m = re.search(r'An error occurred \(([^)]+)\)', str(e))
    return m.group(1) if m else 'unknown error'


def _try(fn, what):
    try:
        fn()
        return True
    except Exception as e:
        log(f'    ⚠ {what} not deleted ({err_code(e)})')
        return False


def _wait(pred, attempts, delay, sleep=None):
    sleep = sleep or time.sleep
    for _ in range(attempts):
        if pred():
            return True
        sleep(delay)
    return pred()


def clean_vpc(ec2, vpc_id, sleep=None, attempts=30, delay=10):
    """Delete a VPC and everything ACK/EKS left in it. Returns True on success.

    Order matters: NAT gateways and interface endpoints own ENIs in the subnets,
    so they are deleted and WAITED for before the subnets; the NAT EIPs can only
    be released once their NAT gateway is gone.
    """
    c = vpc_contents(ec2, vpc_id)
    for nat in c['nat']:
        _try(lambda: ec2.delete_nat_gateway(NatGatewayId=nat['NatGatewayId']),
             f'NAT {nat["NatGatewayId"]}')
    if c['endpoint']:
        _try(lambda: ec2.delete_vpc_endpoints(VpcEndpointIds=_ids(c['endpoint'], 'VpcEndpointId')),
             'VPC endpoints')

    def nats_gone():
        return not ec2.describe_nat_gateways(Filters=[
            {'Name': 'vpc-id', 'Values': [vpc_id]},
            {'Name': 'state', 'Values': ['available', 'pending', 'deleting']}])['NatGateways']
    if c['nat'] and not _wait(nats_gone, attempts, delay, sleep):
        log(f'    ⚠ NAT gateway(s) in {vpc_id} still deleting')

    for igw in c['igw']:
        i = igw['InternetGatewayId']
        _try(lambda: ec2.detach_internet_gateway(InternetGatewayId=i, VpcId=vpc_id), f'detach {i}')
        _try(lambda: ec2.delete_internet_gateway(InternetGatewayId=i), f'IGW {i}')
    for alloc in c['eip']:
        _try(lambda: ec2.release_address(AllocationId=alloc), f'release EIP {alloc}')

    # Async ENIs (NAT, endpoints, AMP scrapers, a deleted cluster's or load balancer's)
    # must clear before subnets go. A detached ("available") ENI is deleted here.
    def enis_clear():
        enis = ec2.describe_network_interfaces(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['NetworkInterfaces']
        for e in enis:
            if e.get('Status') == 'available' and e.get('InterfaceType', '') not in ASYNC_ENI_TYPES:
                _try(lambda: ec2.delete_network_interface(NetworkInterfaceId=e['NetworkInterfaceId']),
                     f'ENI {e["NetworkInterfaceId"]}')
        return not enis
    # ENIs of a just-deleted cluster, load balancer, NAT or endpoint take minutes to go:
    # wait (bounded) rather than stop at the first one, then name what is left.
    if not _wait(enis_clear, attempts, delay, sleep):
        for e in ec2.describe_network_interfaces(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['NetworkInterfaces']:
            log(f'    ⚠ ENI still in VPC: {e["NetworkInterfaceId"]} '
                f'{e.get("InterfaceType", "")} {(e.get("Description") or "")[:50]}')

    for sg in c['sg']:
        if sg.get('IpPermissions'):
            _try(lambda: ec2.revoke_security_group_ingress(
                GroupId=sg['GroupId'], IpPermissions=sg['IpPermissions']), f'revoke {sg["GroupId"]}')
        if sg.get('IpPermissionsEgress'):
            _try(lambda: ec2.revoke_security_group_egress(
                GroupId=sg['GroupId'], IpPermissions=sg['IpPermissionsEgress']), f'revoke {sg["GroupId"]}')
    for sg in c['sg']:
        _try(lambda: ec2.delete_security_group(GroupId=sg['GroupId']), f'SG {sg["GroupId"]}')
    for sn in c['subnet']:
        _try(lambda: ec2.delete_subnet(SubnetId=sn['SubnetId']), f'subnet {sn["SubnetId"]}')
    for rt in c['rt']:
        for a in rt.get('Associations', []):
            if a.get('RouteTableAssociationId') and not a.get('Main'):
                _try(lambda: ec2.disassociate_route_table(AssociationId=a['RouteTableAssociationId']),
                     'disassociate route table')
        _try(lambda: ec2.delete_route_table(RouteTableId=rt['RouteTableId']), f'RT {rt["RouteTableId"]}')
    if _try(lambda: ec2.delete_vpc(VpcId=vpc_id), f'VPC {vpc_id}'):
        log(f'  ✓ deleted VPC {vpc_id}')
        return True
    return False


def run_vpc_sweep(ec2, label, selected, skipped, dry_run, sleep=None):
    for vpc_id, reason in skipped:
        log(f'  skip {label} VPC {vpc_id}: {reason}')
    if not selected:
        log(f'  No {label} VPCs to clean.')
        return 0
    failed = 0
    for vpc_id in selected:
        if dry_run:
            log(f'  [dry-run] would delete {label} VPC {vpc_id}: {describe_plan(ec2, vpc_id)}')
            continue
        log(f'  Cleaning {label} VPC {vpc_id}...')
        if not clean_vpc(ec2, vpc_id, sleep=sleep):
            failed += 1
    return failed


# ---------------------------------------------------------------- RDS

def select_rds(rds, prefix):
    """DevLake databases of this prefix.

    The kro RelationalDatabase RGD names them <prefix>-devlake-* (Aurora cluster,
    its instance and its subnet group). The legacy KubeVela path made standalone
    instances named devlake-* : kept exactly as before so that path is unchanged.
    """
    pre = f'{prefix}-devlake-'
    clusters = [c for c in _paginate(rds.describe_db_clusters, 'DBClusters')
                if c['DBClusterIdentifier'].startswith(pre)]
    cl_ids = {c['DBClusterIdentifier'] for c in clusters}
    instances = [i for i in _paginate(rds.describe_db_instances, 'DBInstances')
                 if i['DBInstanceIdentifier'].startswith(pre)
                 or i.get('DBClusterIdentifier') in cl_ids
                 or (i['DBInstanceIdentifier'].startswith('devlake-')
                     and not i.get('DBClusterIdentifier'))]
    subnet_groups = [g['DBSubnetGroupName'] for g in
                     _paginate(rds.describe_db_subnet_groups, 'DBSubnetGroups')
                     if g['DBSubnetGroupName'].startswith(pre)]
    return clusters, instances, subnet_groups


def _paginate(fn, key, **kw):
    out, marker = [], None
    while True:
        resp = fn(**kw, **({'Marker': marker} if marker else {}))
        out += resp.get(key, [])
        marker = resp.get('Marker')
        if not marker:
            return out


def sweep_rds(rds, prefix, dry_run=False, wait=True, sleep=None, attempts=60, delay=20):
    clusters, instances, subnet_groups = select_rds(rds, prefix)
    if not (clusters or instances or subnet_groups):
        log('  No DevLake RDS resources to clean.')
        return 0
    for i in instances:
        if i.get('DeletionProtection'):
            log(f'  skip RDS instance {i["DBInstanceIdentifier"]}: DeletionProtection is on')
        elif dry_run:
            log(f'  [dry-run] would delete RDS instance {i["DBInstanceIdentifier"]}')
        elif i.get('DBInstanceStatus') != 'deleting':
            # Same flags the previous bash step used for devlake-* instances.
            if _try(lambda: rds.delete_db_instance(
                    DBInstanceIdentifier=i['DBInstanceIdentifier'], SkipFinalSnapshot=True,
                    DeleteAutomatedBackups=True), f'RDS instance {i["DBInstanceIdentifier"]}'):
                log(f'  ✓ initiated RDS deletion: {i["DBInstanceIdentifier"]}')
    for c in clusters:
        cid = c['DBClusterIdentifier']
        if c.get('DeletionProtection'):
            log(f'  skip RDS cluster {cid}: DeletionProtection is on')
        elif dry_run:
            log(f'  [dry-run] would delete RDS cluster {cid} (skip final snapshot)')
        elif c.get('Status') != 'deleting':
            if _try(lambda: rds.delete_db_cluster(DBClusterIdentifier=cid, SkipFinalSnapshot=True),
                    f'RDS cluster {cid}'):
                log(f'  ✓ initiated RDS cluster deletion: {cid}')
    for g in subnet_groups:
        if dry_run:
            log(f'  [dry-run] would delete DB subnet group {g}')
    if dry_run:
        return 0
    if wait:
        def gone():
            c2, i2, _ = select_rds(rds, prefix)
            left = [x for x in c2 if not x.get('DeletionProtection')] + \
                   [x for x in i2 if not x.get('DeletionProtection')]
            return not left
        if not _wait(gone, attempts, delay, sleep):
            log('  ⚠ DevLake RDS still deleting; its ENIs may block the VPC sweep')
    for g in subnet_groups:
        if _try(lambda: rds.delete_db_subnet_group(DBSubnetGroupName=g), f'DB subnet group {g}'):
            log(f'  ✓ deleted DB subnet group {g}')
    return 0


# ---------------------------------------------------------------- log groups

def select_log_groups(logs, prefix, hub, clusters, inventory=None, assume_deleted=()):
    """(selected, [(group, reason)]) EKS log groups of clusters this destroy removed.

    A group /aws/eks/<name>/... is ours when <name> is the hub, starts with
    <prefix>-, or is a cluster the inventory lists with deletionPolicy=delete
    (spokes can have any name). It is kept when <name> is still a live cluster
    or a retained one.
    """
    inventory = inventory or {'clusters': []}
    ours_extra = deleted_clusters(inventory)
    retained = retained_clusters(inventory)
    live = live_clusters(clusters, assume_deleted)
    groups = []
    token = None
    while True:
        kw = {'logGroupNamePrefix': '/aws/eks/'}
        if token:
            kw['nextToken'] = token
        resp = logs.describe_log_groups(**kw)
        groups += [g['logGroupName'] for g in resp.get('logGroups', [])]
        token = resp.get('nextToken')
        if not token:
            break
    selected, skipped = [], []
    for g in sorted(groups):
        parts = g.split('/')
        if len(parts) < 4 or not parts[3]:
            continue
        name = parts[3]
        if not (name == hub or name.startswith(f'{prefix}-') or name in ours_extra):
            continue
        if name in retained:
            skipped.append((g, f'cluster {name} is kept by deletionPolicy=retain'))
        elif name in live:
            skipped.append((g, f'cluster {name} is still {live[name]["status"]}'))
        else:
            selected.append(g)
    return selected, skipped


def sweep_log_groups(logs, selected, skipped, dry_run=False):
    for g, reason in skipped:
        log(f'  skip log group {g}: {reason}')
    for g in selected:
        if dry_run:
            log(f'  [dry-run] would delete log group {g}')
        elif _try(lambda: logs.delete_log_group(logGroupName=g), f'CW log group {g}'):
            log(f'  ✓ deleted CW log group {g}')
    if not selected:
        log('  No EKS log groups to clean.')
    return 0


# ---------------------------------------------------------------- IAM guard

def protected_roles(eks, clusters, assume_deleted=()):
    """Role names still referenced by a live cluster: never sweep them."""
    names = set()

    def add(arn):
        if arn and ':role/' in arn:
            names.add(arn.rsplit('/', 1)[-1])
    for name, c in live_clusters(clusters, assume_deleted).items():
        add(c.get('roleArn'))
        token = None
        while True:
            resp = eks.list_access_entries(clusterName=name, **({'nextToken': token} if token else {}))
            for arn in resp.get('accessEntries', []):
                add(arn)
            token = resp.get('nextToken')
            if not token:
                break
        token = None
        while True:
            resp = eks.list_pod_identity_associations(
                clusterName=name, **({'nextToken': token} if token else {}))
            for a in resp.get('associations', []):
                try:
                    d = eks.describe_pod_identity_association(
                        clusterName=name, associationId=a['associationId'])['association']
                    add(d.get('roleArn'))
                    add(d.get('targetRoleArn'))
                except Exception as e:
                    if 'ResourceNotFound' not in str(e):
                        raise
            token = resp.get('nextToken')
            if not token:
                break
        if not hasattr(eks, 'list_capabilities'):
            continue  # botocore without the EKS capabilities API
        token = None
        while True:
            resp = eks.list_capabilities(clusterName=name, **({'nextToken': token} if token else {}))
            for cap in resp.get('capabilities', []):
                try:
                    d = eks.describe_capability(
                        clusterName=name, capabilityName=cap['capabilityName'])['capability']
                    add(d.get('roleArn'))
                except Exception as e:
                    if 'ResourceNotFound' not in str(e):
                        raise
            token = resp.get('nextToken')
            if not token:
                break
    return names


def parse_common(argv, usage):
    """Tiny argv parser shared by the CLIs: positionals + --dry-run, --inventory,
    --assume-deleted NAME (repeatable, --dry-run only)."""
    pos, opts = [], {'dry_run': False, 'inventory': '', 'assume_deleted': [], 'no_wait': False}
    it = iter(argv)
    for a in it:
        if a == '--dry-run':
            opts['dry_run'] = True
        elif a == '--no-wait':
            opts['no_wait'] = True
        elif a == '--inventory':
            opts['inventory'] = next(it, '')
        elif a == '--assume-deleted':
            opts['assume_deleted'].append(next(it, ''))
        elif a.startswith('--'):
            sys.exit(f'unknown option {a}\n{usage}')
        else:
            pos.append(a)
    if opts['assume_deleted'] and not opts['dry_run']:
        sys.exit('--assume-deleted is only allowed with --dry-run')
    return pos, opts
