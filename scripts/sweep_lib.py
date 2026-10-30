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
  * Never let the hub's own controllers delete an IAM role or policy outside the
    stack's prefix, or a role a live cluster outside the stack still references:
    protect-shared-iam.py marks those managed resources retain/Orphan before the
    addons are removed (hub:destroy-addons step 0).

The "inventory" is a JSON file written by destroy BEFORE the hub is torn down,
while the hub API and kro instances can still be read:
  {"hub_vpc_id": "vpc-...", "clusters": [{"name": "...", "deletionPolicy": "delete"}]}
It is optional: every sweep falls back to AWS tags when it is missing.

"assume_deleted" exists only for --dry-run: it lets an operator preview a
teardown on a live environment by treating the named clusters as already gone.
"""
import json
import os
import re
import sys
import time

PREFIX_TAG = 'platform.gitops.io/prefix'
CLUSTER_TAG = 'platform.gitops.io/cluster'
LIVE = 'live'

# Exit code of a sweep CLI that got no AWS credentials. destroy records it and
# fails at the end instead of printing "Destroy complete" over skipped sweeps.
CREDENTIALS_EXIT = 3
FAILURES_FILE_ENV = 'SWEEP_FAILURES_FILE'
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FAILURES_FILE = os.path.join(_ROOT, 'private', 'destroy-sweep-failures')


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------- credentials
#
# The aws CLI v2 picks the profile from AWS_PROFILE before AWS_DEFAULT_PROFILE;
# botocore (boto3) reads them the other way round. When the environment carries
# both with different values (a shell or sandbox exporting
# AWS_DEFAULT_PROFILE=default while the operator sets AWS_PROFILE=<env>), every
# `aws` call in the Taskfile used <env> while the python helpers used `default`
# and got no credentials. align_profile() makes boto3 follow the CLI's rule.
# It only touches AWS_DEFAULT_PROFILE, so explicit env credentials keep their
# usual precedence over the profile, exactly as for the CLI.

class CredentialsError(Exception):
    """boto3 found no AWS credentials (or they could not be loaded)."""


_CRED_ERRORS = ('NoCredentialsError', 'PartialCredentialsError', 'CredentialRetrievalError',
                'NoAuthTokenError', 'ProfileNotFound', 'TokenRetrievalError', 'SSOTokenLoadError',
                'UnauthorizedSSOTokenError', 'CredentialsError')


def align_profile(environ=None):
    """Make AWS_DEFAULT_PROFILE follow AWS_PROFILE (aws CLI v2 precedence).
    Returns the profile now in effect ('' when none is set)."""
    env = os.environ if environ is None else environ
    prof = env.get('AWS_PROFILE', '')
    if prof and env.get('AWS_DEFAULT_PROFILE') != prof:
        env['AWS_DEFAULT_PROFILE'] = prof
    return prof or env.get('AWS_DEFAULT_PROFILE', '')


def is_credentials_error(e):
    return (any(k.__name__ in _CRED_ERRORS for k in type(e).__mro__)
            or 'Unable to locate credentials' in str(e))


def reraise_credentials(e):
    """Call first in a broad `except Exception` handler: a missing credential is
    not a per-resource failure to log and skip, it must stop the helper."""
    if is_credentials_error(e):
        raise e


_SESSIONS = {}


def session(region=None, boto3_mod=None):
    """A boto3 session using the same profile as the aws CLI, with credentials
    checked up front (raises CredentialsError)."""
    prof = align_profile()
    key = (region, prof)
    if key in _SESSIONS:
        return _SESSIONS[key]
    if boto3_mod is None:
        import boto3 as boto3_mod
    try:
        s = boto3_mod.Session(region_name=region)
        creds = s.get_credentials()
    except Exception as e:
        if is_credentials_error(e):
            raise CredentialsError(f'cannot load AWS credentials for profile {prof or "<none>"} '
                                   f'({type(e).__name__})') from e
        raise
    if creds is None:
        raise CredentialsError(f'no AWS credentials found for profile {prof or "<none>"} '
                               '(the aws CLI and boto3 must see the same credentials)')
    _SESSIONS[key] = s
    return s


def client(service, region=None, boto3_mod=None):
    return session(region, boto3_mod).client(service, region_name=region)


def record_failure(name, path=None):
    path = path or os.environ.get(FAILURES_FILE_ENV) or DEFAULT_FAILURES_FILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a') as f:
            f.write(name + '\n')
    except OSError:
        pass


def run_cli(main, argv, name, failures_path=None):
    """Run a sweep CLI. A credential failure prints a clear error on stderr,
    is recorded for destroy's final check, and exits CREDENTIALS_EXIT."""
    try:
        return main(argv)
    except Exception as e:
        if not is_credentials_error(e):
            raise
        print(f'ERROR {name}: no usable AWS credentials ({e if isinstance(e, CredentialsError) else type(e).__name__}). '
              'Nothing was swept. Check `aws sts get-caller-identity` and AWS_PROFILE / '
              'AWS_DEFAULT_PROFILE, then re-run task destroy.', file=sys.stderr, flush=True)
        record_failure(name, failures_path)
        return CREDENTIALS_EXIT


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
            reraise_credentials(e)
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
            reraise_credentials(e)
            if 'NotFound' not in str(e):
                log(f'  describe-vpcs {hint}: {e}')
    if hub:
        try:
            for v in ec2.describe_vpcs(Filters=[
                    {'Name': f'tag:{PREFIX_TAG}', 'Values': [prefix]},
                    {'Name': f'tag:{CLUSTER_TAG}', 'Values': [hub]}])['Vpcs']:
                found[v['VpcId']] = v
        except Exception as e:
            reraise_credentials(e)
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
    if m:
        return m.group(1)
    return type(e).__name__ if is_credentials_error(e) else 'unknown error'


def _try(fn, what):
    try:
        fn()
        return True
    except Exception as e:
        reraise_credentials(e)
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
    # Disassociate the route tables while their subnets still exist: deleting a
    # subnet drops its association, and disassociating afterwards only fails
    # with InvalidAssociationID.NotFound.
    for rt in c['rt']:
        for a in rt.get('Associations', []):
            if a.get('RouteTableAssociationId') and not a.get('Main'):
                _try(lambda: ec2.disassociate_route_table(AssociationId=a['RouteTableAssociationId']),
                     'disassociate route table')
    for sn in c['subnet']:
        _try(lambda: ec2.delete_subnet(SubnetId=sn['SubnetId']), f'subnet {sn["SubnetId"]}')
    for rt in c['rt']:
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

    A group /aws/eks/<name>/... is ours when <name> is exactly one of this stack's
    clusters (stack_cluster_names: the hub, the inventory's kro cluster instances,
    the legacy <prefix>-spoke-dev/-prod), never by a <prefix>-* wildcard. It is
    kept when <name> is still a live cluster or a retained one.
    """
    inventory = inventory or {'clusters': []}
    ours = stack_cluster_names(prefix, hub, inventory)
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
        if name not in ours:
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


def enabled_regions(ec2):
    """Regions enabled for the account (opt-in regions only once opted in)."""
    return sorted({r['RegionName'] for r in ec2.describe_regions(AllRegions=False).get('Regions', [])})


def protected_roles_all_regions(home, eks_for, regions, assume_deleted=()):
    """IAM is global: a role is protected when a live cluster in ANY enabled region
    references it. assume_deleted (dry-run only) names this stack's clusters, which
    live in the home region. Raises when any region cannot be read: callers keep
    every role (fail closed)."""
    names = set()
    for r in sorted(set(regions) | {home}):
        eks = eks_for(r)
        names |= protected_roles(eks, cluster_inventory(eks), assume_deleted if r == home else ())
    return names


def guard_regions(home, ec2=None, eks=None, eks_for=None):
    """(eks_for, regions) for protected_roles_all_regions. Production: every enabled
    region. Tests inject eks (one fake for every region) and optionally ec2."""
    if eks is not None and eks_for is None:
        eks_for = lambda _r: eks  # noqa: E731
        regions = enabled_regions(ec2) if ec2 is not None else [home]
        return eks_for, regions
    ec2 = ec2 or client('ec2', home)
    eks_for = eks_for or (lambda r: client('eks', r))
    return eks_for, enabled_regions(ec2)


# ------------------------------------------------- shared IAM managed resources
#
# A chart can create an IAM role with a FIXED name, not prefixed by the stack
# (for example an agent observability role every hub creates under the same
# name). Each hub that runs the chart then holds a managed resource for the SAME
# AWS role, with the default deletion policy. Removing one hub's addons makes its
# controller delete the role, which the other hubs' pod identity associations
# still use. Before the addons are removed, destroy marks such resources
# retain/Orphan so the controller forgets them without an AWS delete.

# resource -> (namespaced, family). family picks the patch: Crossplane v1
# (cluster-scoped, spec.deletionPolicy), Crossplane v2 (namespaced, no
# deletionPolicy: drop Delete from managementPolicies), ACK (annotation).
IAM_CR_KINDS = {
    'roles.iam.aws.upbound.io': (False, 'xp1'),
    'policies.iam.aws.upbound.io': (False, 'xp1'),
    'rolepolicyattachments.iam.aws.upbound.io': (False, 'xp1'),
    'roles.iam.aws.m.upbound.io': (True, 'xp2'),
    'policies.iam.aws.m.upbound.io': (True, 'xp2'),
    'rolepolicyattachments.iam.aws.m.upbound.io': (True, 'xp2'),
    'roles.iam.services.k8s.aws': (True, 'ack'),
    'policies.iam.services.k8s.aws': (True, 'ack'),
}
XP_NO_DELETE = ['Observe', 'Create', 'Update', 'LateInitialize']


def iam_cr_aws_role(resource, item):
    """AWS name the CR acts on: the role for a role or an attachment, the policy
    name for a policy. External name first (what Crossplane uses), then ACK's
    spec.name, then the attachment's role, then the object name."""
    meta = item.get('metadata') or {}
    spec = item.get('spec') or {}
    fp = spec.get('forProvider') or {}
    if resource.startswith('rolepolicyattachments.'):
        return fp.get('role') or (fp.get('roleRef') or {}).get('name') or ''
    ext = (meta.get('annotations') or {}).get('crossplane.io/external-name')
    return ext or spec.get('name') or meta.get('name', '')


def already_retained(family, item):
    meta = item.get('metadata') or {}
    spec = item.get('spec') or {}
    if family == 'ack':
        return (meta.get('annotations') or {}).get('services.k8s.aws/deletion-policy') == 'retain'
    if family == 'xp1':
        return spec.get('deletionPolicy') == 'Orphan'
    mp = spec.get('managementPolicies')
    return bool(mp) and 'Delete' not in mp and '*' not in mp


def select_shared_iam_crs(items_by_kind, prefix, protected, guard_ok=True):
    """Managed IAM resources this hub must NOT delete: the AWS name is outside
    <prefix>-, or a live cluster outside this stack still references the role,
    or the reference check failed (fail closed: keep every role CR; the
    prefix-scoped role sweep of steps 3/6b deletes this stack's own leftovers).
    Returns (retain, kept_for_delete): lists of
    (resource, ns, name, aws, reason, already_retained)."""
    retain, delete = [], []
    own = f'{prefix}-'
    for resource, items in items_by_kind.items():
        namespaced, family = IAM_CR_KINDS[resource]
        for it in items:
            meta = it.get('metadata') or {}
            ns = meta.get('namespace', '') if namespaced else ''
            aws = iam_cr_aws_role(resource, it)
            row = (resource, ns, meta.get('name', ''), aws)
            done = already_retained(family, it)
            is_policy = resource.startswith('policies.')
            if not aws.startswith(own):
                retain.append(row + (f'not owned by this stack (outside {own}*)', done))
            elif not is_policy and not guard_ok:
                retain.append(row + ('reference check unavailable (fail closed)', done))
            elif not is_policy and aws in protected:
                retain.append(row + ('still used by a live cluster outside this stack', done))
            else:
                delete.append(row + ('', done))
    return retain, delete


def retain_patch(family):
    """kubectl arguments (after the resource/name) that retain the AWS object."""
    if family == 'ack':
        return ['annotate', '--overwrite', 'services.k8s.aws/deletion-policy=retain']
    if family == 'xp1':
        return ['patch', '--type', 'merge', '-p', json.dumps({'spec': {'deletionPolicy': 'Orphan'}})]
    return ['patch', '--type', 'merge', '-p', json.dumps({'spec': {'managementPolicies': XP_NO_DELETE}})]


def shared_roles_record_path(inventory_path):
    """Where protect-shared-iam.py records the fixed-name roles it retained, next
    to the inventory, for the last-user cleanup after the hub is gone."""
    import os
    return os.path.join(os.path.dirname(inventory_path) or '.', 'shared-iam-retained.json')


def load_shared_roles(path):
    try:
        with open(path) as f:
            return sorted({r for r in json.load(f).get('roles', []) if r})
    except (OSError, ValueError, AttributeError):
        return []


def delete_role(iam, name):
    """Detach managed policies, drop inline policies and instance profiles, delete."""
    for p in _paginate(iam.list_attached_role_policies, 'AttachedPolicies', RoleName=name):
        iam.detach_role_policy(RoleName=name, PolicyArn=p['PolicyArn'])
    for p in _paginate(iam.list_role_policies, 'PolicyNames', RoleName=name):
        iam.delete_role_policy(RoleName=name, PolicyName=p)
    for ip in _paginate(iam.list_instance_profiles_for_role, 'InstanceProfiles', RoleName=name):
        iam.remove_role_from_instance_profile(InstanceProfileName=ip['InstanceProfileName'], RoleName=name)
    iam.delete_role(RoleName=name)


def sweep_shared_roles(iam, names, protected, dry_run=False):
    """Delete the recorded shared roles once no live cluster references them (this
    stack was the last user). Returns (deleted, kept) name lists."""
    deleted, kept = [], []
    for name in names:
        if name in protected:
            log(f'  keep shared role {name}: still used by a live EKS cluster')
            kept.append(name)
            continue
        if dry_run:
            log(f'  would delete shared role {name} (no live cluster references it)')
            deleted.append(name)
            continue
        try:
            delete_role(iam, name)
            log(f'  deleted shared role {name} (no live cluster references it)')
            deleted.append(name)
        except Exception as e:
            reraise_credentials(e)
            if err_code(e) == 'NoSuchEntity':
                log(f'  shared role {name} already gone')
                continue
            log(f'    ⚠ shared role {name} not deleted ({err_code(e)})')
            kept.append(name)
    return deleted, kept


# ------------------------------------------- hub leftovers (EBS, TGs, log delivery)
#
# Found by a real teardown: things the controllers leave once the hub is gone.
#   * EBS volumes of PVCs whose StorageClass is Retain (status available, tag
#     kubernetes.io/cluster/<cluster>=owned);
#   * target groups of the load-balancer-controller (step 1 deletes the ALBs only);
#   * CloudWatch Logs delivery sources/destinations of the EKS capability logs
#     (step 2 deletes the deliveries only).
# Each is scoped to a cluster of THIS stack (stack_cluster_names: exact names, no
# <prefix>-* wildcard) that is no longer live, so a live or retained cluster's
# resources, and another stack whose prefix starts with ours, are never touched.

LEGACY_SPOKES = ('spoke-dev', 'spoke-prod')


def stack_cluster_names(prefix, hub, inventory=None):
    """The clusters of THIS stack, by exact name: the hub, every kro cluster instance
    the inventory recorded (spokes can have any name), and the legacy
    <prefix>-spoke-dev/-prod spokes (the same set step 6ei uses for AMP scrapers).
    Never a <prefix>-* wildcard: destroying prefix "peeks" must not select the
    resources of a "peeks-a-hub" that shares the account or the hosted zone."""
    names = {hub} | {c.get('name') for c in (inventory or {}).get('clusters', [])}
    names |= {f'{prefix}-{s}' for s in LEGACY_SPOKES}
    return {n for n in names if n}


def _stack_cluster(name, prefix, hub, inventory=None):
    return bool(name) and name in stack_cluster_names(prefix, hub, inventory)


def gone_stack_clusters(prefix, hub, clusters, inventory=None, assume_deleted=()):
    """Predicate: cluster name belongs to this stack and is neither live nor retained."""
    live = set(live_clusters(clusters, assume_deleted))
    retained = retained_clusters(inventory or {})
    ours = stack_cluster_names(prefix, hub, inventory)
    return lambda n: bool(n) and n in ours and n not in live and n not in retained


EKS_CLUSTER_NAME_TAG = 'eks:eks-cluster-name'


def volume_owners(v):
    """Clusters an EBS volume belongs to: the in-tree/OSS CSI driver tags
    kubernetes.io/cluster/<name>=owned, the EKS Auto Mode CSI driver tags
    eks:eks-cluster-name=<name>."""
    tags = v.get('Tags') or []
    owners = [t['Key'].split('/', 2)[2] for t in tags
              if t['Key'].startswith('kubernetes.io/cluster/') and t.get('Value') == 'owned']
    owners += [t['Value'] for t in tags if t['Key'] == EKS_CLUSTER_NAME_TAG and t.get('Value')]
    return list(dict.fromkeys(owners))


def select_ebs_volumes(ec2, is_gone):
    sel, skipped = [], []
    for v in _paginate_token(ec2.describe_volumes, 'Volumes',
                             Filters=[{'Name': 'status', 'Values': ['available']}]):
        owners = volume_owners(v)
        if not owners:
            continue
        if any(is_gone(o) for o in owners):
            sel.append((v['VolumeId'], owners[0]))
        else:
            skipped.append((v['VolumeId'], owners[0]))
    return sel, skipped


def select_target_groups(elbv2, is_gone):
    tgs = _paginate_token(elbv2.describe_target_groups, 'TargetGroups', token_in='Marker', token_out='NextMarker')
    sel, skipped = [], []
    for i in range(0, len(tgs), 20):
        chunk = tgs[i:i + 20]
        tags = {d['ResourceArn']: {t['Key']: t['Value'] for t in d.get('Tags', [])}
                for d in elbv2.describe_tags(ResourceArns=[t['TargetGroupArn'] for t in chunk])['TagDescriptions']}
        for t in chunk:
            cl = tags.get(t['TargetGroupArn'], {}).get('elbv2.k8s.aws/cluster', '')
            if not cl:
                continue
            if is_gone(cl) and not t.get('LoadBalancerArns'):
                sel.append((t['TargetGroupArn'], cl))
            else:
                skipped.append((t['TargetGroupArn'], cl))
    return sel, skipped


def select_log_deliveries(logs, hub, hub_gone):
    """Delivery sources/destinations named after the hub, once the hub is gone and
    no delivery references them."""
    if not hub_gone:
        return [], []
    used_src, used_dst = set(), set()
    for d in _paginate_token(logs.describe_deliveries, 'deliveries', 'nextToken'):
        used_src.add(d.get('deliverySourceName', ''))
        used_dst.add(d.get('deliveryDestinationArn', ''))
    srcs = [s['name'] for s in _paginate_token(logs.describe_delivery_sources, 'deliverySources', 'nextToken')
            if hub in s.get('name', '') and s['name'] not in used_src]
    dsts = [d['name'] for d in _paginate_token(logs.describe_delivery_destinations, 'deliveryDestinations', 'nextToken')
            if hub in d.get('name', '') and d.get('arn', '') not in used_dst]
    return srcs, dsts


# external-dns (registry txt, txtOwnerId = the cluster name) writes, next to each
# record it manages, a TXT record "heritage=external-dns,external-dns/owner=<id>,...".
# Its name is the record's name with a "<type>-" prefix (new format) or the same
# name (legacy format). destroy removes external-dns together with the addons, so
# the records of the hub's ingresses (alias to a load balancer that is gone)
# stay in the zone. Only these are swept: A/AAAA/CNAME records owned by a removed
# cluster of the stack, plus their TXT registry records. Never a hosted zone, an
# NS/SOA, a record without an external-dns owner TXT (ACM validation CNAMEs,
# hand-made records), a "_"-prefixed name, or a record of another owner.
DNS_OWNER_RE = re.compile(r'heritage=external-dns,.*?external-dns/owner=([^,"]+)')
DNS_TYPE_PREFIXES = {'a-': ('A',), 'aaaa-': ('AAAA',), 'cname-': ('CNAME', 'A')}
DNS_DATA_TYPES = ('A', 'AAAA', 'CNAME')


def _fqdn(n):
    return n.rstrip('.').lower() + '.'


def _zone_matches(zone_name, domain):
    z, d = _fqdn(zone_name), _fqdn(domain)
    return d == z or d.endswith('.' + z)


def dns_owner(rrset):
    if rrset.get('Type') != 'TXT':
        return ''
    for r in rrset.get('ResourceRecords') or []:
        m = DNS_OWNER_RE.search(r.get('Value', ''))
        if m:
            return m.group(1)
    return ''


def select_dns_records(r53, domain, is_gone):
    """[(zone_id, zone_name, [rrsets to delete])], [(name, owner)] kept.
    Only hosted zones the ingress domain belongs to (external-dns domainFilters +
    --aws-zone-match-parent); nothing when no domain is configured."""
    if not domain:
        return [], []
    plans, kept = [], []
    for z in _paginate_token(r53.list_hosted_zones, 'HostedZones', token_in='Marker', token_out='NextMarker'):
        if not _zone_matches(z['Name'], domain):
            continue
        zid = z['Id'].rsplit('/', 1)[-1]
        rrsets, kw = [], {'HostedZoneId': zid}
        while True:
            resp = r53.list_resource_record_sets(**kw)
            rrsets += resp.get('ResourceRecordSets', [])
            if not resp.get('IsTruncated'):
                break
            kw.update(StartRecordName=resp['NextRecordName'], StartRecordType=resp['NextRecordType'])
            if resp.get('NextRecordIdentifier'):
                kw['StartRecordIdentifier'] = resp['NextRecordIdentifier']
        by_name = {}
        for rr in rrsets:
            by_name.setdefault(_fqdn(rr['Name']), []).append(rr)
        delete, seen = [], set()

        def add(rr):
            k = (_fqdn(rr['Name']), rr['Type'], rr.get('SetIdentifier', ''))
            if k not in seen:
                seen.add(k)
                delete.append(rr)
        for rr in rrsets:
            owner = dns_owner(rr)
            name = _fqdn(rr['Name'])
            if not owner or name.startswith('_') or not name.endswith(_fqdn(z['Name'])):
                continue
            if not is_gone(owner):
                kept.append((name, owner))
                continue
            first, _, rest = name.partition('.')
            targets = [(name, DNS_DATA_TYPES)]  # legacy format: same name
            for pfx, types in DNS_TYPE_PREFIXES.items():
                if first.startswith(pfx) and len(first) > len(pfx):
                    targets = [(first[len(pfx):] + '.' + rest, types)]
                    break
            add(rr)
            for tname, types in targets:
                for data in by_name.get(tname, []):
                    if data['Type'] in types and not tname.startswith('_'):
                        add(data)
        if delete:
            # Data records first, then their TXT registry records.
            delete.sort(key=lambda r: r['Type'] == 'TXT')
            plans.append((zid, z['Name'], delete))
    return plans, kept


def sweep_dns_records(r53, plans, dry_run=False):
    n = 0
    verb = 'would delete' if dry_run else 'delete'
    for zid, zname, rrsets in plans:
        for rr in rrsets:
            log(f'  {verb} Route53 {rr["Type"]} {rr["Name"]} (zone {zname.rstrip(".")}, external-dns owner removed)')
        if dry_run:
            continue
        changes = [{'Action': 'DELETE', 'ResourceRecordSet': rr} for rr in rrsets]
        if _try(lambda: r53.change_resource_record_sets(
                HostedZoneId=zid, ChangeBatch={'Comment': 'kind-kro-ack destroy: external-dns leftovers',
                                               'Changes': changes}), f'Route53 records in {zname}'):
            n += len(rrsets)
    return n


def _paginate_token(fn, key, token_in='NextToken', token_out=None, **kw):
    """Generic pager: token_in is the request parameter, token_out the response key."""
    token_out = token_out or token_in
    out, tok = [], None
    while True:
        resp = fn(**kw, **({token_in: tok} if tok else {}))
        out += resp.get(key, [])
        tok = resp.get(token_out)
        if not tok:
            return out


def sweep_hub_leftovers(ec2, elbv2, logs, prefix, hub, clusters, inventory=None,
                        dry_run=False, assume_deleted=(), r53=None, domain=''):
    is_gone = gone_stack_clusters(prefix, hub, clusters, inventory, assume_deleted)
    verb = 'would delete' if dry_run else 'delete'
    n = 0
    vols, vkeep = select_ebs_volumes(ec2, is_gone)
    for vid, cl in vkeep:
        log(f'  keep EBS volume {vid}: cluster {cl} is live, retained or not this stack')
    for vid, cl in vols:
        log(f'  {verb} EBS volume {vid} (available, owned by removed cluster {cl})')
        if not dry_run and _try(lambda: ec2.delete_volume(VolumeId=vid), f'EBS volume {vid}'):
            n += 1
    tgs, _ = select_target_groups(elbv2, is_gone)
    for arn, cl in tgs:
        name = arn.rsplit('/', 2)[-2] if arn.count('/') >= 2 else arn
        log(f'  {verb} target group {name} (no load balancer, cluster {cl} removed)')
        if not dry_run and _try(lambda: elbv2.delete_target_group(TargetGroupArn=arn), f'target group {name}'):
            n += 1
    srcs, dsts = select_log_deliveries(logs, hub, is_gone(hub))
    for s in srcs:
        log(f'  {verb} CloudWatch Logs delivery source {s}')
        if not dry_run and _try(lambda: logs.delete_delivery_source(name=s), f'delivery source {s}'):
            n += 1
    for d in dsts:
        log(f'  {verb} CloudWatch Logs delivery destination {d}')
        if not dry_run and _try(lambda: logs.delete_delivery_destination(name=d), f'delivery destination {d}'):
            n += 1
    dns = []
    if r53 is not None and domain:
        plans, dkeep = select_dns_records(r53, domain, is_gone)
        for name, owner in dkeep:
            log(f'  keep Route53 records of {name}: external-dns owner {owner} is live, retained or not this stack')
        dns = [f'{rr["Type"]} {rr["Name"]}' for _, _, rrs in plans for rr in rrs]
        n += sweep_dns_records(r53, plans, dry_run)
    return {'volumes': [v for v, _ in vols], 'target_groups': [a for a, _ in tgs],
            'delivery_sources': srcs, 'delivery_destinations': dsts, 'dns_records': dns, 'deleted': n}


def parse_common(argv, usage):
    """Tiny argv parser shared by the CLIs: positionals + --dry-run, --inventory,
    --assume-deleted NAME (repeatable, --dry-run only)."""
    pos, opts = [], {'dry_run': False, 'inventory': '', 'assume_deleted': [], 'no_wait': False, 'domain': ''}
    it = iter(argv)
    for a in it:
        if a == '--dry-run':
            opts['dry_run'] = True
        elif a == '--no-wait':
            opts['no_wait'] = True
        elif a == '--inventory':
            opts['inventory'] = next(it, '')
        elif a == '--domain':
            opts['domain'] = next(it, '')
        elif a == '--assume-deleted':
            opts['assume_deleted'].append(next(it, ''))
        elif a.startswith('--'):
            sys.exit(f'unknown option {a}\n{usage}')
        else:
            pos.append(a)
    if opts['assume_deleted'] and not opts['dry_run']:
        sys.exit('--assume-deleted is only allowed with --dry-run')
    return pos, opts
