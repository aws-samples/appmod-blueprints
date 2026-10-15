"""Hermetic tests for kind-kro-ack `task destroy` steps 6ei (AMP scrapers) and 6i
(IDE-VPC security groups): a stack's teardown touches only its own resources.

The two shell blocks are read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml
and run with bash against a fake `aws` on PATH: a small Python script that answers the
describe/list calls from a fixture, applies --query with jmespath (as the AWS CLI does),
and records every other call. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_taskfile_scope.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

jmespath = pytest.importorskip("jmespath")  # ships with botocore, which the sweep needs
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")

FAKE_AWS = r'''#!{python}
import json, os, sys
import jmespath
fx = json.load(open(os.environ["FAKE_AWS_FIXTURE"]))
svc, op, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
opts, i = {{}}, 0
while i < len(rest):
    if rest[i].startswith("--") and i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        opts[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        i += 1
def filt(spec):  # "Name=k,Values=v"
    name, values = spec.split(",Values=")
    return name.split("=", 1)[1], values
def tagd(o):
    return {{t["Key"]: t["Value"] for t in o.get("Tags") or []}}
if not op.startswith(("describe-", "list-", "get-")):
    with open(os.environ["FAKE_AWS_LOG"], "a") as f:
        f.write(json.dumps([svc, op, opts]) + "\n")
    sys.exit(0)
if (svc, op) == ("eks", "list-clusters"):
    out = {{"clusters": list(fx["clusters"])}}
elif (svc, op) == ("eks", "describe-cluster"):
    out = {{"cluster": {{"name": opts["name"], "tags": fx["clusters"][opts["name"]]}}}}
elif (svc, op) == ("amp", "list-scrapers"):
    out = {{"scrapers": fx["scrapers"]}}
elif (svc, op) == ("ec2", "describe-vpcs"):
    vpcs = fx["vpcs"]
    if "vpc-ids" in opts:
        vpcs = [v for v in vpcs if v["VpcId"] == opts["vpc-ids"]]
    if "filters" in opts:
        name, values = filt(opts["filters"])
        assert name.startswith("tag:") and values == "*", opts
        vpcs = [v for v in vpcs if name[4:] in tagd(v)]
    out = {{"Vpcs": vpcs}}
elif (svc, op) == ("ec2", "describe-security-groups"):
    sgs = [g for gs in fx["sgs"].values() for g in gs]
    if "group-ids" in opts:
        sgs = [g for g in sgs if g["GroupId"] == opts["group-ids"]]
    if "filters" in opts:
        name, values = filt(opts["filters"])
        assert name == "vpc-id", opts
        sgs = fx["sgs"].get(values, [])
    out = {{"SecurityGroups": sgs}}
else:
    out = {{}}
if "query" in opts:
    out = jmespath.search(opts["query"], out)
def text(v):
    if v is None:
        return "None"
    if isinstance(v, list):
        if v and all(isinstance(x, list) for x in v):
            return "\n".join("\t".join(text(y) for y in x) for x in v)
        return "\t".join(text(x) for x in v)
    return json.dumps(v) if isinstance(v, dict) else str(v)
print(json.dumps(out) if opts.get("output") == "json" else text(out))
'''


def _block(start, stop):
    """The shell lines of one destroy step, dedented, from its comment to `stop`."""
    lines = open(TASKFILE).read().splitlines()
    i = next(n for n, line in enumerate(lines) if line.strip().startswith(start))
    indent = len(lines[i]) - len(lines[i].lstrip())
    out = []
    for line in lines[i:]:
        if out and line.strip() and stop(line, indent):
            break
        out.append(line[indent:])
    return "\n".join(out)


STEP_6EI = _block("# 6ei.", lambda line, ind: line.strip().startswith("# 6eii."))
STEP_6I = _block("# 6i.", lambda line, ind: len(line) - len(line.lstrip()) < ind)


def _tags(**kv):
    return [{"Key": k, "Value": v} for k, v in kv.items()]


def _cfn_vpc(vpc_id, stack, **kv):
    return {"VpcId": vpc_id, "Tags": _tags(**{
        "aws:cloudformation:stack-id": f"arn:aws:cloudformation:us-west-2:111122223333:stack/{stack}/x",
        "aws:cloudformation:stack-name": stack, "Name": "peeks-workshop/IDE-VPC", **kv})}


def _sgs(vpc_id):
    # a workshop-created SG with a cross-SG rule, and the stack's own (CFN) SG (#1031)
    return [
        {"GroupId": f"sg-{vpc_id}-hub", "GroupName": "eks-cluster-sg", "Tags": [],
         "IpPermissions": [{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": f"sg-{vpc_id}-hub"}]}]},
        {"GroupId": f"sg-{vpc_id}-ide", "GroupName": "ide",
         "Tags": _tags(**{"aws:cloudformation:stack-name": "x"}), "IpPermissions": []},
    ]


def _arn(c):
    return f"arn:aws:eks:us-west-2:111122223333:cluster/{c}"


STACK1 = _cfn_vpc("vpc-stack1", "peeks-workshop-main", ResourcePrefix="peeks")  # older template
STACK2 = _cfn_vpc("vpc-stack2", "pvt-workshop", ResourcePrefix="peeks",
                  **{"platform.gitops.io/prefix": "pvt"})  # published template
OTHER = _cfn_vpc("vpc-other", "network-workshop-prod")
FIXTURE = {
    "clusters": {"peeks-hub": {}, "peeks-spoke-dev": {}, "peeks-spoke-prod": {},
                 "pvt-hub": {}, "pvt-spoke-dev": {},
                 "pvt-team-a": {"platform.gitops.io/prefix": "pvt"}, "unrelated": {}},
    "scrapers": [{"scraperId": f"s-{c}", "source": {"eksConfiguration": {"clusterArn": _arn(c)}}}
                 for c in ("peeks-hub", "peeks-spoke-dev", "peeks-spoke-prod",
                           "pvt-hub", "pvt-spoke-dev", "pvt-team-a", "unrelated")]
    + [{"scraperId": "s-no-eks-source", "source": {}}],
    "vpcs": [STACK1, STACK2, OTHER],
}


def _run(tmp_path, step, prefix, vpcs=None):
    fx = dict(FIXTURE, vpcs=vpcs if vpcs is not None else FIXTURE["vpcs"])
    fx["sgs"] = {v["VpcId"]: _sgs(v["VpcId"]) for v in fx["vpcs"]}
    (tmp_path / "fixture.json").write_text(json.dumps(fx))
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    aws = bindir / "aws"
    aws.write_text(FAKE_AWS.format(python=sys.executable))
    aws.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(f'REGION="us-west-2"; PREFIX="{prefix}"\nHUB="{prefix}-hub"\n{step}\n')
    log = tmp_path / "writes.jsonl"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_AWS_FIXTURE=str(tmp_path / "fixture.json"), FAKE_AWS_LOG=str(log))
    res = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_6ei_deletes_only_this_stacks_scrapers(tmp_path):
    writes = _run(tmp_path, STEP_6EI, "pvt")
    assert sorted(o["scraper-id"] for _s, op, o in writes if op == "delete-scraper") == \
        ["s-pvt-hub", "s-pvt-spoke-dev", "s-pvt-team-a"]
    writes = _run(tmp_path, STEP_6EI, "peeks")
    assert sorted(o["scraper-id"] for _s, op, o in writes if op == "delete-scraper") == \
        ["s-peeks-hub", "s-peeks-spoke-dev", "s-peeks-spoke-prod"]


def _sg_writes(writes):
    return sorted((op, o["group-id"]) for _s, op, o in writes if "security-group" in op)


def test_6i_never_touches_another_stacks_ide_vpc(tmp_path):
    # Today's account: only stack 1. A second stack's teardown writes nothing.
    assert _sg_writes(_run(tmp_path, STEP_6I, "pvt", vpcs=[STACK1])) == []
    # Both stacks present: each clears only its own workshop-created SG.
    for prefix, own in (("pvt", "vpc-stack2"), ("peeks", "vpc-stack1")):
        assert _sg_writes(_run(tmp_path, STEP_6I, prefix)) == [
            ("delete-security-group", f"sg-{own}-hub"),
            ("revoke-security-group-ingress", f"sg-{own}-hub"),
        ], prefix


def test_6i_single_stack_finds_its_own_ide_vpc(tmp_path):
    # Self-paced and Workshop Studio stack names (template without the prefix tag), and
    # any stack name when the VPC carries platform.gitops.io/prefix=<prefix>.
    for vpc in (_cfn_vpc("vpc-own", "peeks-workshop"),
                _cfn_vpc("vpc-own", "peeks-workshop-team-stack"),
                _cfn_vpc("vpc-own", "tCaT-appmod-test-abc", **{"platform.gitops.io/prefix": "peeks"})):
        assert _sg_writes(_run(tmp_path, STEP_6I, "peeks", vpcs=[vpc, OTHER])) == [
            ("delete-security-group", "sg-vpc-own-hub"),
            ("revoke-security-group-ingress", "sg-vpc-own-hub"),
        ], vpc["Tags"]
    # A prefix tag naming another prefix wins over a matching stack name.
    tagged_other = _cfn_vpc("vpc-own", "peeks-workshop", **{"platform.gitops.io/prefix": "pvt"})
    assert _sg_writes(_run(tmp_path, STEP_6I, "peeks", vpcs=[tagged_other])) == []
