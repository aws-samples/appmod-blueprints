"""Hermetic tests: seed-observability must not store a spoke's AMP scraper inputs while the
spoke is still CREATING.

A spoke EKS cluster that is CREATING already has an ARN and subnets, but no cluster security
group yet. `aws eks describe-cluster --query ...clusterSecurityGroupId --output text` then
prints the literal "None", which the seed used to write to <hub>/config as
spoke_<env>_security_group_id. The observability-aws chart skips a spoke Scraper whose
security group is "None", so the spoke never got a scraper. The seed now waits (bounded) for a
CREATING spoke to leave CREATING, and never writes "None"/"null"/"" scraper inputs.

The spoke block of seed-observability is read verbatim from both provider Taskfiles and run
under go-task. `aws` and `sleep` are fakes on PATH. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_observability_spoke_sg_race.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RESOLVER = os.path.join(REPO, "scripts", "resolve-spoke-cluster.sh")
PROVIDERS = ("kind-kro-ack", "kind-crossplane")
TASK = shutil.which("task")
HUB, PREFIX, REGION = "acme-hub", "acme", "us-west-2"
COLORS = ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP", "C_WARN")

pytestmark = pytest.mark.skipif(TASK is None, reason="go-task not on PATH")

# st["clusters"][name] = {"creating_polls": N}: the cluster answers CREATING (no security
# group, "None") to the first N status reads, then ACTIVE with sg-<name>. N = -1: CREATING
# forever. Every non-status read reflects the state reached by the status reads so far.
FAKE_AWS = r'''#!{python} -I
import json, os, sys
p = os.environ["FAKE_STATE"]
st = json.load(open(p))
svc, op, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
opts, i = {}, 0
while i < len(rest):
    if rest[i].startswith("--") and i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        opts[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        i += 1
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(["aws", svc, op, opts]) + "\n")
cl = st["clusters"]
def creating(c):
    return c["creating_polls"] < 0 or c.get("polls", 0) < c["creating_polls"]
if svc == "eks" and op == "describe-cluster":
    name, q = opts["name"], opts["query"]
    c = cl.get(name)
    if c is None:
        sys.stderr.write("ResourceNotFoundException\n"); sys.exit(254)
    if q == "cluster.status":
        print("CREATING" if creating(c) else "ACTIVE")
        c["polls"] = c.get("polls", 0) + 1
    elif q.startswith("cluster.[tags"):
        print("\t".join([PREFIX_TAG, "dev" if name.endswith("dev") else "prod",
                         "CREATING" if creating(c) else "ACTIVE"]))
    elif q == "cluster.arn":
        print("arn:aws:eks:us-west-2:111122223333:cluster/%s" % name)
    elif q == "cluster.resourcesVpcConfig.subnetIds[]":
        print("subnet-%s-1\tsubnet-%s-2" % (name, name))
    elif q == "cluster.resourcesVpcConfig.clusterSecurityGroupId":
        print("None" if creating(c) else "sg-" + name)
    else:
        sys.stderr.write("fake aws: unexpected query %s\n" % q); sys.exit(2)
elif svc == "ec2" and op == "describe-subnets":
    print("\t".join(opts["subnet-ids"].split()))
elif svc == "secretsmanager" and op == "get-secret-value":
    print(st["secrets"][opts["secret-id"]])
elif svc == "secretsmanager" and op == "put-secret-value":
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(["put", opts["secret-id"], opts["secret-string"]]) + "\n")
else:
    sys.stderr.write("fake aws: unexpected call %s %s\n" % (svc, op)); sys.exit(2)
json.dump(st, open(p, "w"))
'''

FAKE_SLEEP = '''#!/bin/sh
printf '["sleep", "%s"]\\n' "$1" >> "$FAKE_LOG"
'''


def _spoke_block(provider):
    with open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")) as f:
        cmds = yaml.safe_load(f)["tasks"]["secrets-manager:seed-observability"]["cmds"]
    text = next(c for c in cmds if isinstance(c, str) and "Populate spoke scraper values" in c)
    return text[text.index("# Populate spoke scraper values"):
                text.index("# Update Keycloak SAML client with AMG URL")]


def _run(tmp_path, provider, clusters, meta=None, env_extra=None):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable)
                                .replace("PREFIX_TAG", repr(PREFIX)))
    (bindir / "sleep").write_text(FAKE_SLEEP)
    for f in ("aws", "sleep"):
        (bindir / f).chmod(0o755)
    st, log = tmp_path / "state.json", tmp_path / "calls.jsonl"
    st.write_text(json.dumps({"clusters": clusters, "secrets": {
        f"{HUB}/config": json.dumps({"metadata": json.dumps(meta or {"aws_grafana_url": "g"})})}}))
    log.write_text("")
    (tmp_path / "scripts").mkdir()
    shutil.copy(RESOLVER, tmp_path / "scripts")
    tvars = dict({k: "" for k in COLORS}, HUB_CLUSTER_NAME=HUB, RESOURCE_PREFIX=PREFIX, AWS_REGION=REGION)
    tf = tmp_path / "Taskfile.yaml"
    tf.write_text(yaml.safe_dump({"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": tvars,
                                  "tasks": {"run": {"cmds": [_spoke_block(provider)]}}}, sort_keys=False))
    env = {k: v for k, v in os.environ.items() if k != "SPOKE_SCRAPER_WAIT_TRIES"}
    env.update(PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(st), FAKE_LOG=str(log),
               **(env_extra or {}))
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    calls = [json.loads(l) for l in log.read_text().splitlines() if l]
    puts = [c for c in calls if c[0] == "put"]
    meta_out = json.loads(json.loads(puts[-1][2])["metadata"]) if puts else None
    return res, meta_out, calls


def _spokes(dev_polls, prod_polls):
    return {f"{PREFIX}-spoke-dev": {"creating_polls": dev_polls},
            f"{PREFIX}-spoke-prod": {"creating_polls": prod_polls}}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_creating_spoke_is_waited_for_and_gets_its_real_security_group(tmp_path, provider):
    # spoke-dev turns ACTIVE after 3 CREATING reads; spoke-prod is already ACTIVE.
    res, meta, calls = _run(tmp_path, provider, _spokes(3, 0))
    assert res.returncode == 0, res.stdout + res.stderr
    assert meta["spoke_dev_security_group_id"] == f"sg-{PREFIX}-spoke-dev", meta
    assert meta["spoke_prod_security_group_id"] == f"sg-{PREFIX}-spoke-prod", meta
    assert meta["spoke_dev_cluster_arn"].endswith(f"cluster/{PREFIX}-spoke-dev")
    assert [c for c in calls if c[0] == "sleep"], "a CREATING spoke must be polled with a sleep"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_spoke_still_creating_after_the_wait_never_stores_none(tmp_path, provider):
    # spoke-dev never leaves CREATING within the (shortened) wait: its inputs must stay empty
    # (the converge gate re-seeds once it is ACTIVE), never "None"; spoke-prod is wired.
    res, meta, calls = _run(tmp_path, provider, _spokes(-1, 0), env_extra={"SPOKE_SCRAPER_WAIT_TRIES": "2"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "None" not in json.dumps(meta), meta
    assert meta["spoke_dev_security_group_id"] == "" and meta["spoke_dev_cluster_arn"] == "", meta
    assert meta["spoke_prod_security_group_id"] == f"sg-{PREFIX}-spoke-prod", meta
    assert "no cluster security group yet" in res.stdout and f"{PREFIX}-spoke-dev" in res.stdout, res.stdout
    assert len([c for c in calls if c[0] == "sleep"]) == 2, calls


@pytest.mark.parametrize("provider", PROVIDERS)
def test_wait_tries_value_that_is_not_a_number_falls_back_to_the_default(tmp_path, provider):
    res, meta, _ = _run(tmp_path, provider, _spokes(1, 0), env_extra={"SPOKE_SCRAPER_WAIT_TRIES": "abc"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert meta["spoke_dev_security_group_id"] == f"sg-{PREFIX}-spoke-dev", meta


@pytest.mark.parametrize("provider", PROVIDERS)
def test_active_spokes_are_not_polled(tmp_path, provider):
    res, meta, calls = _run(tmp_path, provider, _spokes(0, 0))
    assert res.returncode == 0, res.stdout + res.stderr
    assert not [c for c in calls if c[0] == "sleep"], calls
    assert meta["spoke_dev_security_group_id"] == f"sg-{PREFIX}-spoke-dev"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_both_spokes_still_creating_write_nothing(tmp_path, provider):
    # Neither spoke has usable inputs: no put at all (nothing over any earlier good value).
    res, meta, _ = _run(tmp_path, provider, _spokes(-1, -1), env_extra={"SPOKE_SCRAPER_WAIT_TRIES": "1"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert meta is None, meta
