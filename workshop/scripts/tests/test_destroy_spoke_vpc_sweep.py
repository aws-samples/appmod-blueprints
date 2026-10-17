"""Hermetic tests for kind-kro-ack `task destroy` step 6h (`scripts/sweep-spoke-vpcs.py`):
the spoke-VPC sweep never touches the stack's own IDE/hub VPC.

The self-paced template stamps `platform.gitops.io/prefix=<prefix>` on the IDE VPC (step
6i relies on it), and the hub runs in that VPC. A sweep that selects spoke VPCs by that
tag alone "cleans" the IDE VPC like a spoke: it deletes its NAT gateway and route tables
and revokes its security groups, cutting the network of the IDE that runs `task destroy`.

The step-6 cmd is read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and run
under go-task's own interpreter with the Taskfile's `set:` options (bash with the same
options if go-task is not on PATH). `aws` is a fake on PATH that answers the CLI's
list/describe calls (with --query applied by jmespath, as the CLI does), and `boto3` is a
fake package on PYTHONPATH for the python helpers (6a, 6h). Both answer from one fixture
and record every other call; nothing is ever sent and no wait is slept. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_spoke_vpc_sweep.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
jmespath = pytest.importorskip("jmespath")  # ships with botocore, which the sweep needs
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
REGION = "us-west-2"

FAKE_BOTO3 = r'''
import json, os, time
time.sleep = lambda *a, **k: None  # the sweep's NAT/ENI waits are simulated, not slept
_FX = json.load(open(os.environ["FAKE_AWS_FIXTURE"]))
_KEYS = {"describe_vpcs": ("vpcs", "Vpcs"), "describe_nat_gateways": ("nats", "NatGateways"),
         "describe_internet_gateways": ("igws", "InternetGateways"),
         "describe_subnets": ("subnets", "Subnets"), "describe_route_tables": ("rts", "RouteTables"),
         "describe_security_groups": ("sgs", "SecurityGroups"),
         "describe_network_interfaces": ("enis", "NetworkInterfaces")}
def _tags(o):
    return {t["Key"]: t["Value"] for t in o.get("Tags") or []}
def _match(o, filters):
    for f in filters or []:
        name, values = f["Name"], f.get("Values", [])
        if name.startswith("tag:"):
            ok = _tags(o).get(name[4:]) in values
        elif name == "vpc-id":
            ok = o.get("VpcId") in values
        elif name == "attachment.vpc-id":
            ok = any(a.get("VpcId") in values for a in o.get("Attachments", []))
        elif name == "state":
            ok = o.get("State") in values
        else:
            raise AssertionError("fake boto3: unexpected filter %s" % name)
        if not ok:
            return False
    return True
class _Client:
    def __init__(self, svc):
        self._svc = svc
    def __getattr__(self, op):
        def call(**kw):
            if op.startswith(("describe_", "list_", "get_")):
                if self._svc != "ec2":
                    return {}
                key, out = _KEYS[op]
                items = [o for o in _FX[key] if _match(o, kw.get("Filters") or kw.get("Filter"))]
                if "VpcIds" in kw:
                    items = [o for o in items if o["VpcId"] in kw["VpcIds"]]
                return {out: items}
            with open(os.environ["FAKE_AWS_LOG"], "a") as f:
                f.write(json.dumps(["boto3", self._svc, op, kw]) + "\n")
            return {}
        return call
def client(svc, **kw):
    return _Client(svc)
'''

FAKE_AWS = r'''#!{python} -I
import json, os, sys
import jmespath
fx = json.load(open(os.environ["FAKE_AWS_FIXTURE"]))
svc, op, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
opts, i = {}, 0
while i < len(rest):
    if rest[i].startswith("--") and i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        opts[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        opts[rest[i][2:]] = ""; i += 1
if not op.startswith(("describe-", "list-", "get-")):
    with open(os.environ["FAKE_AWS_LOG"], "a") as f:
        f.write(json.dumps(["cli", svc, op, opts]) + "\n")
    sys.exit(0)
with open(os.environ["FAKE_AWS_LOG"], "a") as f:
    f.write(json.dumps(["cli-read", svc, op, opts]) + "\n")
def tagd(o):
    return {t["Key"]: t["Value"] for t in o.get("Tags") or []}
out = {
    ("iam", "list-roles"): {"Roles": []}, ("iam", "list-policies"): {"Policies": []},
    ("secretsmanager", "list-secrets"): {"SecretList": []},
    ("amp", "list-workspaces"): {"workspaces": []}, ("amp", "list-scrapers"): {"scrapers": []},
    ("eks", "list-clusters"): {"clusters": []}, ("rds", "describe-db-instances"): {"DBInstances": []},
    ("sts", "get-caller-identity"): {"Account": "111122223333"},
    ("iam", "list-open-id-connect-providers"): {"OpenIDConnectProviderList": []},
    ("logs", "describe-log-groups"): {"logGroups": []},
}.get((svc, op), {})
if (svc, op) == ("ec2", "describe-vpcs"):
    vpcs = fx["vpcs"]
    if "vpc-ids" in opts:
        vpcs = [v for v in vpcs if v["VpcId"] == opts["vpc-ids"]]
    if "filters" in opts:
        name, values = opts["filters"].split(",Values=")
        name = name.split("=", 1)[1]
        assert name.startswith("tag:") and values == "*", opts
        vpcs = [v for v in vpcs if name[4:] in tagd(v)]
    out = {"Vpcs": vpcs}
elif (svc, op) == ("ec2", "describe-security-groups"):
    sgs = fx["sgs"]
    if "group-ids" in opts:
        sgs = [g for g in sgs if g["GroupId"] == opts["group-ids"]]
    if "filters" in opts:
        name, values = opts["filters"].split(",Values=")
        assert name == "Name=vpc-id", opts
        sgs = [g for g in sgs if g["VpcId"] == values]
    out = {"SecurityGroups": sgs}
if "query" in opts:
    out = jmespath.search(opts["query"], out)
def text(v):
    if v is None:
        return "None"
    if isinstance(v, list):
        return "\t".join(text(x) for x in v)
    return json.dumps(v) if isinstance(v, dict) else str(v)
print(json.dumps(out) if opts.get("output") == "json" else text(out))
'''


def _tags(**kv):
    return [{"Key": k, "Value": v} for k, v in kv.items()]


def _cfn(stack, logical):
    return {"aws:cloudformation:stack-name": stack, "aws:cloudformation:logical-id": logical,
            "aws:cloudformation:stack-id": f"arn:aws:cloudformation:{REGION}:111122223333:stack/{stack}/x"}


def _network(fx, vpc, vpc_tags, sgs=(), enis=()):
    """One VPC as the run had it: 2 public + 2 private subnets, a main route table, a
    public and a private route table (associated), a NAT gateway with an EIP, an IGW."""
    fx["vpcs"].append({"VpcId": vpc, "Tags": _tags(**vpc_tags)})
    subnets = [f"{vpc}-sn-pub1", f"{vpc}-sn-pub2", f"{vpc}-sn-priv1", f"{vpc}-sn-priv2"]
    fx["subnets"] += [{"SubnetId": s, "VpcId": vpc} for s in subnets]
    fx["rts"] += [
        {"RouteTableId": f"{vpc}-rtb-main", "VpcId": vpc,
         "Associations": [{"Main": True, "RouteTableAssociationId": f"{vpc}-assoc-main"}]},
        {"RouteTableId": f"{vpc}-rtb-pub", "VpcId": vpc, "Associations": [
            {"Main": False, "SubnetId": s, "RouteTableAssociationId": f"{vpc}-assoc-{s}"} for s in subnets[:2]]},
        {"RouteTableId": f"{vpc}-rtb-priv", "VpcId": vpc, "Associations": [
            {"Main": False, "SubnetId": s, "RouteTableAssociationId": f"{vpc}-assoc-{s}"} for s in subnets[2:]]},
    ]
    fx["nats"].append({"NatGatewayId": f"{vpc}-nat", "VpcId": vpc, "State": "available",
                       "NatGatewayAddresses": [{"AllocationId": f"{vpc}-eipalloc"}]})
    fx["igws"].append({"InternetGatewayId": f"{vpc}-igw", "Attachments": [{"VpcId": vpc}]})
    fx["sgs"].append({"GroupId": f"{vpc}-sg-default", "GroupName": "default", "VpcId": vpc, "Tags": []})
    for name, tags in sgs:
        fx["sgs"].append({"GroupId": f"{vpc}-sg-{name}", "GroupName": name, "VpcId": vpc,
                          "Tags": _tags(**tags),
                          "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                                             "IpRanges": [{"CidrIp": "10.0.0.0/16"}]}],
                          "IpPermissionsEgress": [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]})
    for eni, kind in enis:
        fx["enis"].append({"NetworkInterfaceId": f"{vpc}-{eni}", "VpcId": vpc,
                           "InterfaceType": kind, "Description": eni})


def _ide_vpc(fx, vpc, stack, prefix):
    # The published self-paced template's IDE VPC: CDK path Name, literal ResourcePrefix
    # "peeks", ResourceType ideHubVPC, the stack's CFN tags and the ownership prefix tag.
    _network(fx, vpc, {"Name": "peeks-workshop/IDE-VPC", "ResourcePrefix": "peeks", "ManagedBy": "CDK",
                       "ResourceType": "ideHubVPC", "platform.gitops.io/prefix": prefix,
                       **_cfn(stack, "IDEVPCFFC40728")},
             sgs=[("ide", {**_cfn(stack, "PEEKSIDEIdeSecurityGroup"), "platform.gitops.io/prefix": prefix}),
                  ("efs", {**_cfn(stack, "PEEKSIDEEfsSecurityGroup"), "platform.gitops.io/prefix": prefix}),
                  (f"{prefix}-amg-sg", {"platform.gitops.io/prefix": prefix})],
             enis=[("eni-ide", "interface"), ("eni-efs-a", "efs"), ("eni-efs-b", "efs")])


def _spoke_vpc(fx, vpc, cluster, prefix):
    # An ACK spoke VPC from the kro VPC RGD (no ENIs left: its cluster is already deleted).
    _network(fx, vpc, {"Name": f"{cluster}-vpc", "eks:kubernetes-resource-name": f"{cluster}-vpc",
                       "eks:kubernetes-namespace": cluster, "eks:kubernetes-api-group": "ec2.services.k8s.aws",
                       "platform.gitops.io/prefix": prefix, "platform.gitops.io/cluster": cluster},
             sgs=[("eks-cluster-sg", {"platform.gitops.io/cluster": cluster})])


def _fixture():
    return {"vpcs": [], "subnets": [], "rts": [], "nats": [], "igws": [], "sgs": [], "enis": []}


def _run_step6(tmp_path, fx, prefix, hub):
    with open(TASKFILE) as f:
        tf = yaml.safe_load(f)
    cmd = next(c["cmd"] for c in tf["tasks"]["destroy"]["cmds"]
               if isinstance(c, dict) and "# 6h." in c.get("cmd", ""))
    cmd = cmd.replace("{{.ROOT_DIR}}", REPO)
    bindir, pylib = tmp_path / "bin", tmp_path / "pylib" / "boto3"
    bindir.mkdir()
    pylib.mkdir(parents=True)
    (pylib / "__init__.py").write_text(FAKE_BOTO3)
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    for b in ("aws", "python3"):
        (bindir / b).chmod(0o755)
    fixture, log = tmp_path / "fixture.json", tmp_path / "calls.jsonl"
    fixture.write_text(json.dumps(fx))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", PYTHONPATH=str(tmp_path / "pylib"),
               FAKE_AWS_FIXTURE=str(fixture), FAKE_AWS_LOG=str(log))
    tvars = {"AWS_REGION": REGION, "RESOURCE_PREFIX": prefix, "HUB_CLUSTER_NAME": hub}
    opts = tf.get("set", [])
    if TASK:
        t = tmp_path / "Taskfile.yml"
        t.write_text(yaml.safe_dump({"version": "3", "set": opts, "vars": tvars,
                                     "tasks": {"run": {"cmds": [{"cmd": cmd}]}}}, sort_keys=False))
        res = subprocess.run([TASK, "-s", "-t", str(t), "run"], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=180)
    else:
        for k, v in tvars.items():
            cmd = cmd.replace("{{.%s}}" % k, v)
        script = tmp_path / "step6.sh"
        script.write_text("".join(f"set -o {o}\n" for o in opts) + cmd)
        res = subprocess.run(["bash", str(script)], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=180)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return res, calls


def _touches(call, vpc):
    """A recorded write whose arguments name the VPC or one of its resources."""
    return vpc in json.dumps(call[-1])


def _writes(calls):
    return [c for c in calls if c[0] in ("boto3", "cli")]


@pytest.fixture(scope="module")
def the_run(tmp_path_factory):
    """Mirrors the 2026-10-16 teardown: this stack (prefix tdv, hub in the IDE VPC, two
    ACK spokes), next to another workshop stack (prefix peeks) with the same layout."""
    fx = _fixture()
    _ide_vpc(fx, "vpc-tdv-ide", "tdv-workshop", "tdv")
    _spoke_vpc(fx, "vpc-tdv-dev", "tdv-spoke-dev", "tdv")
    _spoke_vpc(fx, "vpc-tdv-prod", "tdv-spoke-prod", "tdv")
    _ide_vpc(fx, "vpc-peeks-ide", "peeks-workshop-main", "peeks")
    _spoke_vpc(fx, "vpc-peeks-dev", "peeks-spoke-dev", "peeks")
    _spoke_vpc(fx, "vpc-peeks-prod", "peeks-spoke-prod", "peeks")
    return _run_step6(tmp_path_factory.mktemp("destroy-6h"), fx, "tdv", "tdv-hub")


def test_ide_vpc_is_never_cleaned_as_a_spoke(the_run):
    res, calls = the_run
    hits = [c for c in _writes(calls) if c[0] == "boto3" and _touches(c, "vpc-tdv-ide")]
    assert hits == [], "6h wrote to the IDE/hub VPC:\n" + "\n".join(
        f"  {c[2]} {json.dumps(c[3])}" for c in hits)
    assert "Cleaning spoke VPC vpc-tdv-ide" not in res.stdout, res.stdout


def test_spoke_vpcs_are_still_cleaned(the_run):
    _, calls = the_run
    ops = [(c[2], json.dumps(c[3])) for c in _writes(calls) if c[0] == "boto3"]
    for vpc in ("vpc-tdv-dev", "vpc-tdv-prod"):
        for op, ident in (("delete_nat_gateway", f"{vpc}-nat"), ("delete_internet_gateway", f"{vpc}-igw"),
                          ("delete_subnet", f"{vpc}-sn-priv1"), ("delete_route_table", f"{vpc}-rtb-pub"),
                          ("release_address", f"{vpc}-eipalloc"), ("delete_vpc", f'"{vpc}"')):
            assert any(o == op and ident in a for o, a in ops), f"{op} {ident} missing"


def test_other_stack_is_untouched(the_run):
    _, calls = the_run
    hits = [c for c in _writes(calls) if "vpc-peeks-" in json.dumps(c[-1])]
    assert hits == [], hits


def test_step6_runs_to_the_end_and_6i_still_clears_the_ide_vpc_sgs(the_run):
    res, calls = the_run
    assert res.returncode == 0, res.stdout + res.stderr
    # 6i (aws CLI) runs after 6h and deletes only the IDE VPC's workshop-created SG.
    sg = [(c[2], c[3].get("group-id")) for c in _writes(calls) if c[0] == "cli" and "security-group" in c[2]]
    assert sg == [("delete-security-group", "vpc-tdv-ide-sg-tdv-amg-sg")], sg


def test_selection_rules(tmp_path):
    """Legacy-named spoke VPCs (pre-tag installs) are still swept; a kro-made hub VPC, a
    prefix-tagged VPC without a cluster tag, and any CloudFormation-owned VPC are not."""
    fx = _fixture()
    _network(fx, "vpc-legacy", {"Name": "acme-spoke-dev-vpc", "eks:kubernetes-resource-name": "acme-spoke-dev-vpc"})
    _network(fx, "vpc-team-a", {"platform.gitops.io/prefix": "acme", "platform.gitops.io/cluster": "acme-team-a"})
    _network(fx, "vpc-hub", {"Name": "acme-hub-vpc", "platform.gitops.io/prefix": "acme",
                             "platform.gitops.io/cluster": "acme-hub"})
    _network(fx, "vpc-no-cluster", {"platform.gitops.io/prefix": "acme"})
    _network(fx, "vpc-cfn", {"platform.gitops.io/prefix": "acme", "platform.gitops.io/cluster": "acme-x",
                             **_cfn("network-stack", "Vpc")})
    res, calls = _run_step6(tmp_path, fx, "acme", "acme-hub")
    assert res.returncode == 0, res.stdout + res.stderr
    deleted = sorted(c[3]["VpcId"] for c in _writes(calls) if c[0] == "boto3" and c[2] == "delete_vpc")
    assert deleted == ["vpc-legacy", "vpc-team-a"], res.stdout
