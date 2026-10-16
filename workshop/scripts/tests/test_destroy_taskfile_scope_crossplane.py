"""Hermetic tests for kind-crossplane `task destroy`: a stack's teardown touches only its
own AWS resources, and still selects all of its own Crossplane VPCs and EIPs.

Every destroy step that calls `aws` (plus hub:destroy-addons' secret deletes) is read
from cluster-providers/kind-crossplane/Taskfile.yaml, rendered for a prefix, and run with
bash under the Taskfile's `set: [errexit, nounset, pipefail]` against a fake `aws` on
PATH. The fake answers describe/list calls from a two-stack fixture, applies --filters
and --query (jmespath) as the AWS CLI does, and records every other call. Each recorded
call is attributed to the stack that owns the resource it names. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_taskfile_scope_crossplane.py -q
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

jmespath = pytest.importorskip("jmespath")  # ships with botocore, which the sweep needs
yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-crossplane", "Taskfile.yaml")
REGION, ACCOUNT = "us-west-2", "111122223333"

FAKE_AWS = r'''#!{python}
import fnmatch, json, os, sys
import jmespath
fx = json.load(open(os.environ["FAKE_AWS_FIXTURE"]))
log = os.environ["FAKE_AWS_LOG"]
args = sys.argv[1:]
svc, op, rest = args[0], args[1], args[2:]
opts, key = {{}}, None
for a in rest:  # --opt v1 v2 ... (several values for --filters / --filter)
    if a.startswith("--"):
        key = a[2:]; opts.setdefault(key, [])
    elif key is not None:
        opts[key].append(a)
one = lambda k: (opts.get(k) or [None])[0]
if not op.startswith(("describe-", "list-", "get-")):
    with open(log, "a") as f:
        f.write(json.dumps([svc, op, opts]) + "\n")
    sys.exit(0)
deleted = {{v for w in map(json.loads, open(log)) if w[1].startswith(("delete-", "release-"))
           for vs in w[2].values() for v in vs}}  # deleted resources stop being listed
def tagd(r):
    t = r.get("Tags") or []
    return {{x["Key"]: x["Value"] for x in t}} if isinstance(t, list) else t
def match(r, spec):  # "Name=<name>,Values=a,b,..."; AND across filters, as EC2 does
    name, values = spec.split(",Values=", 1)
    name, values = name.split("=", 1)[1], values.split(",")
    if name.startswith("tag:"):
        v = tagd(r).get(name[4:])
        return v is not None and any(fnmatch.fnmatchcase(v, p) for p in values)
    if name == "tag-key":
        return any(k in values for k in tagd(r))
    if name == "attachment.vpc-id":
        return any(a["VpcId"] in values for a in r.get("Attachments", []))
    field = {{"vpc-id": "VpcId", "state": "State"}}[name]
    return r.get(field) in values
def ec2(kind):
    rs = [r for r in fx["ec2"][kind] if r["_id"] not in deleted]
    for spec in opts.get("filters", []) + opts.get("filter", []):
        rs = [r for r in rs if match(r, spec)]
    return rs
cluster = one("name") or one("cluster-name")
if (svc, op) == ("eks", "list-clusters"):
    out = {{"clusters": sorted(fx["live_clusters"])}}
elif (svc, op) == ("eks", "describe-cluster"):
    if cluster not in fx["live_clusters"]:
        sys.stderr.write("An error occurred (ResourceNotFoundException) when calling the "
                         "DescribeCluster operation: No cluster found for name: %s.\n" % cluster)
        sys.exit(254)
    out = {{"cluster": {{"name": cluster, "status": "ACTIVE", "tags": fx["live_clusters"][cluster]}}}}
elif (svc, op) == ("eks", "list-capabilities"):
    out = {{"capabilities": []}}
elif (svc, op) == ("eks", "list-pod-identity-associations"):
    out = {{"associations": []}}
elif (svc, op) == ("iam", "list-roles"):
    out = {{"Roles": [{{"RoleName": r}} for r in fx["roles"]]}}
elif (svc, op) == ("iam", "list-policies"):
    out = {{"Policies": [{{"PolicyName": p.rsplit("/", 1)[-1], "Arn": p}} for p in fx["policies"]]}}
elif svc == "iam":  # attached/inline policies, policy versions: none
    out = {{"AttachedPolicies": [], "PolicyNames": [], "Versions": []}}
elif (svc, op) == ("amp", "list-scrapers"):
    out = {{"scrapers": [s for s in fx["scrapers"] if s["scraperId"] not in deleted]}}
elif (svc, op) == ("amp", "list-workspaces"):
    out = {{"workspaces": [{{"workspaceId": w}} for w in fx["amp"]]}}
elif (svc, op) == ("amp", "list-tags-for-resource"):
    out = {{"tags": fx["amp"].get(one("resource-arn").rsplit("/", 1)[-1], {{}})}}
elif (svc, op) == ("grafana", "list-workspaces"):
    out = {{"workspaces": [{{"id": w}} for w in fx["amg"]]}}
elif (svc, op) == ("grafana", "describe-workspace"):
    out = {{"workspace": {{"id": one("workspace-id"), "tags": fx["amg"].get(one("workspace-id"), {{}})}}}}
elif (svc, op) == ("secretsmanager", "list-secrets"):
    out = {{"SecretList": [{{"Name": n}} for n in fx["secrets"]]}}
elif (svc, op) == ("elbv2", "describe-load-balancers"):
    out = {{"LoadBalancers": [r for r in fx["elbv2"]["lbs"] if r["_id"] not in deleted]}}
elif (svc, op) == ("elbv2", "describe-target-groups"):
    out = {{"TargetGroups": [r for r in fx["elbv2"]["tgs"] if r["_id"] not in deleted]}}
elif svc == "ec2":
    kind = {{"describe-vpcs": "Vpcs", "describe-addresses": "Addresses",
            "describe-nat-gateways": "NatGateways", "describe-vpc-endpoints": "VpcEndpoints",
            "describe-internet-gateways": "InternetGateways", "describe-subnets": "Subnets",
            "describe-route-tables": "RouteTables",
            "describe-security-groups": "SecurityGroups"}}[op]
    rs = ec2(kind)
    for k in ("vpc-ids", "group-ids", "allocation-ids"):
        if k in opts:
            rs = [r for r in rs if r["_id"] in opts[k]]
    out = {{kind: rs}}
else:
    raise SystemExit("fake aws: unhandled %s %s" % (svc, op))
if "query" in opts:
    out = jmespath.search(one("query"), out)
def text(v):
    if v is None:
        return "None"
    if isinstance(v, list):
        if v and all(isinstance(x, list) for x in v):
            return "\n".join("\t".join(text(y) for y in x) for x in v)
        return "\t".join(text(x) for x in v)
    return json.dumps(v) if isinstance(v, dict) else str(v)
print(json.dumps(out) if one("output") == "json" else text(out))
'''


# ── fixture ─────────────────────────────────────────────────────────────────────
def _tags(**kv):
    return [{"Key": k, "Value": v} for k, v in kv.items()]


def _cluster_tags(cluster, prefix):
    # The Composition's `tags` patchSet, on the VPC, EIP and every networking resource.
    return {"platform.gitops.io/cluster": cluster, "platform.gitops.io/prefix": prefix}


def _cfn_tags(stack):
    return {"aws:cloudformation:stack-name": stack,
            "aws:cloudformation:stack-id": f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{stack}/x"}


def _stack(prefix, spokes):
    """One kind-crossplane workshop stack on the published template: a Crossplane VPC (and
    its dependencies, EIP, scraper) per cluster, the CFN IDE VPC with the prefix tag but no
    cluster tag, AMP/AMG workspaces, IAM and secrets. Returns (resources, owned ids)."""
    hub = f"{prefix}-hub"
    res = {k: [] for k in ("Vpcs", "Addresses", "NatGateways", "VpcEndpoints",
                           "InternetGateways", "Subnets", "RouteTables", "SecurityGroups")}
    lbs, tgs, scrapers = [], [], []

    def network(vpc, tags):
        res["Vpcs"].append({"_id": vpc, "VpcId": vpc, "Tags": _tags(**tags)})
        res["Subnets"].append({"_id": f"subnet-{vpc}", "SubnetId": f"subnet-{vpc}", "VpcId": vpc})
        res["RouteTables"] += [
            {"_id": f"rtb-{vpc}", "RouteTableId": f"rtb-{vpc}", "VpcId": vpc,
             "Associations": [{"Main": False}]},
            {"_id": f"rtb-main-{vpc}", "RouteTableId": f"rtb-main-{vpc}", "VpcId": vpc,
             "Associations": [{"Main": True}]}]
        res["InternetGateways"].append({"_id": f"igw-{vpc}", "InternetGatewayId": f"igw-{vpc}",
                                        "Attachments": [{"VpcId": vpc}]})
        res["NatGateways"].append({"_id": f"nat-{vpc}", "NatGatewayId": f"nat-{vpc}",
                                   "VpcId": vpc, "State": "available"})
        res["VpcEndpoints"].append({"_id": f"vpce-{vpc}", "VpcEndpointId": f"vpce-{vpc}",
                                    "VpcId": vpc})
        res["SecurityGroups"] += [
            {"_id": f"sg-{vpc}", "GroupId": f"sg-{vpc}", "GroupName": f"{vpc}-sg", "VpcId": vpc,
             "IpPermissions": [{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": f"sg-{vpc}"}]}],
             "IpPermissionsEgress": []},
            {"_id": f"sg-default-{vpc}", "GroupId": f"sg-default-{vpc}", "GroupName": "default",
             "VpcId": vpc, "IpPermissions": [], "IpPermissionsEgress": []}]
        lb = f"arn:aws:elasticloadbalancing:{REGION}:{ACCOUNT}:loadbalancer/app/{vpc}/1"
        tg = f"arn:aws:elasticloadbalancing:{REGION}:{ACCOUNT}:targetgroup/{vpc}/1"
        lbs.append({"_id": lb, "LoadBalancerArn": lb, "VpcId": vpc})
        tgs.append({"_id": tg, "TargetGroupArn": tg, "VpcId": vpc})

    for c in [hub, *spokes]:
        network(f"vpc-{c}", _cluster_tags(c, prefix))
        res["Addresses"].append({"_id": f"eipalloc-{c}", "AllocationId": f"eipalloc-{c}",
                                 "Tags": _tags(**_cluster_tags(c, prefix))})
    ide = f"vpc-{prefix}-ide"
    network(ide, {**_cfn_tags(f"{prefix}-workshop"), "Name": "peeks-workshop/IDE-VPC",
                  "platform.gitops.io/prefix": prefix})
    res["Addresses"].append({"_id": f"eipalloc-{prefix}-ide", "AllocationId": f"eipalloc-{prefix}-ide",
                             "Tags": _tags(**_cfn_tags(f"{prefix}-workshop"),
                                           **{"platform.gitops.io/prefix": prefix})})
    # observability-aws: <prefix>-<hub> for the hub; spoke scrapers only for the clusters
    # hub:seed-observability finds, <prefix>-spoke-dev/-prod.
    for c in [hub, *spokes]:
        if c == hub or c in (f"{prefix}-spoke-dev", f"{prefix}-spoke-prod"):
            alias = f"{prefix}-{c}" if c == hub else f"{prefix}-{c[len(prefix) + 1:]}"
            scrapers.append({"scraperId": f"s-{c}", "alias": alias, "status": {"statusCode": "ACTIVE"},
                             "source": {"eksConfiguration": {
                                 "clusterArn": f"arn:aws:eks:{REGION}:{ACCOUNT}:cluster/{c}"}}})
    data = {
        "ec2": res, "elbv2": {"lbs": lbs, "tgs": tgs}, "scrapers": scrapers,
        "amp": {f"ws-{prefix}": {"crossplane-name": f"{prefix}-amp"}},
        "amg": {f"g-{prefix}": {"crossplane-name": f"{prefix}-amg"}},
        "roles": [f"{hub}-external-dns", f"{hub}-cluster-role"],
        "policies": [f"arn:aws:iam::{ACCOUNT}:policy/{hub}-external-dns-policy"],
        "secrets": [f"{hub}/config", f"{hub}/keycloak", f"{hub}/langfuse-otel"],
        "clusters": {c: {"platform.gitops.io/prefix": prefix} for c in [hub, *spokes]},
    }
    owned = {r["_id"] for rs in res.values() for r in rs} | {r["_id"] for r in lbs + tgs}
    owned |= {s["scraperId"] for s in scrapers} | set(data["amp"]) | set(data["amg"])
    owned |= set(data["roles"]) | set(data["policies"]) | set(data["secrets"])
    owned |= set(data["clusters"])
    return data, owned


# Stack 1 names its spokes as the workshop does (spokes:enable-crossplane <prefix>-spoke-*).
# Stack 2 uses the literal names of the commented example in
# gitops/fleet/spoke-values/tenants/workshop/crossplane-clusters/values.yaml.
STACKS = {"peeks": ["peeks-spoke-dev", "peeks-spoke-prod"], "pvt": ["spoke-dev", "spoke-prod"]}


def _account(stacks):
    built = {p: _stack(p, spokes) for p, spokes in stacks.items()}
    fx = {"ec2": {}, "elbv2": {"lbs": [], "tgs": []}, "scrapers": [], "amp": {}, "amg": {},
          "roles": [], "policies": [], "secrets": [], "clusters": {}}
    for data, _owned in built.values():
        for k, rs in data["ec2"].items():
            fx["ec2"].setdefault(k, []).extend(rs)
        for k in ("lbs", "tgs"):
            fx["elbv2"][k] += data["elbv2"][k]
        for k in ("scrapers", "roles", "policies", "secrets"):
            fx[k] += data[k]
        for k in ("amp", "amg", "clusters"):
            fx[k].update(data[k])
    return fx, {p: owned for p, (_d, owned) in built.items()}


# ── rendering and running ───────────────────────────────────────────────────────
def _aws_steps(prefix, config):
    """The destroy cmds that call aws, plus hub:destroy-addons' `aws ...` cmds, rendered."""
    tasks = yaml.safe_load(open(TASKFILE))["tasks"]
    subs = {"AWS_REGION": REGION, "AWS_ACCOUNT_ID": ACCOUNT, "RESOURCE_PREFIX": prefix,
            "HUB_CLUSTER_NAME": f"{prefix}-hub", "CONFIG_FILE": config}
    steps = []
    for task in ("hub:destroy-addons", "destroy"):
        for c in tasks[task]["cmds"]:
            text = c.get("cmd", "") if isinstance(c, dict) else c if isinstance(c, str) else ""
            if not re.search(r"(^|\s|\$\()aws ", text) or re.search(r"kubectl|helm |kind ", text):
                continue
            for k, v in subs.items():
                text = text.replace("{{." + k + "}}", v)
            assert "{{" not in text, text
            steps.append(text)
    return steps


_RUNS = {}


@pytest.fixture
def run(tmp_path_factory):
    """run(prefix[, stacks]) -> (writes, owned ids per stack, [(step, rc, stderr)]), once per
    (prefix, account): the teardown is deterministic and each run spawns ~100 fake calls."""
    def _cached(prefix, stacks=STACKS):
        key = (prefix, json.dumps(stacks, sort_keys=True))
        if key not in _RUNS:
            _RUNS[key] = _run(tmp_path_factory.mktemp("xp"), prefix, stacks)
        return _RUNS[key]
    return _cached


def _run(tmp_path, prefix, stacks):
    fx, owned = _account(stacks)
    # At destroy time this stack's clusters are gone; the other stacks' are still running.
    fx["live_clusters"] = {c: t for c, t in fx["clusters"].items() if c not in owned[prefix]}
    (tmp_path / "fixture.json").write_text(json.dumps(fx))
    (tmp_path / "config.yaml").write_text(f"resourcePrefix: {prefix}\nhub:\n  clusterName: {prefix}-hub\n")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS.format(python=sys.executable))
    (bindir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    if not shutil.which("yq"):  # the config has no .spokes, so SPOKE_PREFIXES is empty
        (bindir / "yq").write_text("#!/bin/sh\nexit 0\n")
    for f in bindir.iterdir():
        f.chmod(0o755)
    log = tmp_path / "writes.jsonl"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_AWS_FIXTURE=str(tmp_path / "fixture.json"), FAKE_AWS_LOG=str(log))
    rcs = []
    for i, step in enumerate(_aws_steps(prefix, str(tmp_path / "config.yaml"))):
        script = tmp_path / f"step{i}.sh"
        script.write_text("set -euo pipefail\n" + step)
        res = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=120)
        assert "fake aws: unhandled" not in res.stderr, res.stderr
        rcs.append((step, res.returncode, res.stderr))
    writes = [json.loads(line) for line in log.read_text().splitlines()]
    return writes, owned, rcs


def _targets(writes):
    """(op, resource id) for every resource a recorded write call names."""
    return {(op, v) for _svc, op, opts in writes for k, vs in opts.items()
            if k not in ("region", "output", "query", "ip-permissions") for v in vs}


def _owner(owned, rid):
    return next((p for p, ids in owned.items() if rid in ids), None)


# ── tests ───────────────────────────────────────────────────────────────────────
def test_changed_steps_run_clean_under_the_taskfile_shell_options(run):
    _writes, _owned, rcs = run("peeks")
    for step, rc, err in rcs:
        if "list-scrapers" in step or "describe-vpcs" in step:
            assert rc == 0, err


@pytest.mark.parametrize("prefix", ["peeks", "pvt"])
def test_teardown_never_writes_to_the_other_stack(run, prefix):
    writes, owned, _ = run(prefix)
    foreign = sorted((op, rid) for op, rid in _targets(writes)
                     if _owner(owned, rid) not in (None, prefix))
    assert foreign == [], foreign


@pytest.mark.parametrize("prefix", ["peeks", "pvt"])
def test_teardown_selects_all_of_its_own_crossplane_vpcs_and_eips(run, prefix):
    writes, _owned, _ = run(prefix)
    t = _targets(writes)
    clusters = [f"{prefix}-hub", *STACKS[prefix]]
    assert sorted(v for op, v in t if op == "delete-vpc") == sorted(f"vpc-{c}" for c in clusters)
    assert sorted(v for op, v in t if op == "release-address") == \
        sorted(f"eipalloc-{c}" for c in clusters)
    # Everything inside those VPCs, and nothing in the stack's own IDE VPC (CFN-owned,
    # carries the prefix tag but no cluster tag).
    for c in clusters:
        vpc = f"vpc-{c}"
        assert {("delete-subnet", f"subnet-{vpc}"), ("delete-route-table", f"rtb-{vpc}"),
                ("delete-internet-gateway", f"igw-{vpc}"), ("delete-nat-gateway", f"nat-{vpc}"),
                ("delete-vpc-endpoints", f"vpce-{vpc}"), ("delete-security-group", f"sg-{vpc}"),
                ("revoke-security-group-ingress", f"sg-{vpc}")} <= t, c
    assert not [v for _op, v in t if f"{prefix}-ide" in v]


def test_teardown_deletes_only_its_own_scrapers_and_workspaces(run):
    for prefix, own in (("peeks", ["s-peeks-hub", "s-peeks-spoke-dev", "s-peeks-spoke-prod"]),
                        ("pvt", ["s-pvt-hub"])):
        writes, _owned, _ = run(prefix)
        t = _targets(writes)
        assert sorted(v for op, v in t if op == "delete-scraper") == own, prefix
        assert sorted(v for op, v in t if op == "delete-workspace") == [f"g-{prefix}", f"ws-{prefix}"]


def test_a_prefix_that_extends_ours_with_a_dash_is_another_stack(run):
    # resourcePrefix allows "-" (config.schema.json), so "peeks" and "peeks-2" can coexist.
    # The alias match "peeks-*" claimed every "peeks-2-..." scraper.
    stacks = {"peeks": STACKS["peeks"], "peeks-2": ["peeks-2-spoke-dev", "peeks-2-spoke-prod"]}
    for prefix in stacks:
        writes, owned, _ = run(prefix, stacks)
        foreign = sorted((op, rid) for op, rid in _targets(writes)
                         if _owner(owned, rid) not in (None, prefix))
        assert foreign == [], (prefix, foreign)
        assert sorted(v for op, v in _targets(writes) if op == "delete-scraper") == \
            [f"s-{prefix}-hub", f"s-{prefix}-spoke-dev", f"s-{prefix}-spoke-prod"]
