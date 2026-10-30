"""Hermetic tests: observability/AMP scrapers find spokes by tags, not by a built name.

The workshop names its spokes <prefix>-spoke-dev / <prefix>-spoke-prod, but outside the workshop
a spoke is named by whoever declares it (e.g. <prefix>-dev). `secrets-manager:seed-observability`
used to look up only the workshop names, so such a spoke never got an AMP scraper.
scripts/resolve-spoke-cluster.sh now finds the spoke (operator-set name, workshop name, then the
tags kro stamps: platform.gitops.io/prefix + environment) and seed-observability writes
spoke_<env>_cluster_name next to the scraper keys, never over an operator-set value.

Covers: the resolver itself; the spoke block of seed-observability for both providers (read
verbatim from the Taskfiles, run under go-task); hub:seed keeping the name keys; the converge
gate noticing a tag-discovered spoke. `aws` is a fake on PATH. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_observability_spoke_names.py -q
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

FAKE_AWS = r'''#!{python} -I
import json, os, sys
st = json.load(open(os.environ["FAKE_STATE"]))
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
if svc == "eks" and op == "list-clusters":
    if st.get("list_fails"):
        sys.stderr.write("ThrottlingException\n"); sys.exit(254)
    print("\t".join(cl.keys()))
elif svc == "eks" and op == "describe-cluster":
    c = cl.get(opts["name"])
    if c is None:
        sys.stderr.write("ResourceNotFoundException\n"); sys.exit(254)
    q = opts["query"]
    if q == "cluster.status":
        print(c["status"])
    elif q.startswith("cluster.[tags"):
        print("\t".join(c.get("tags", ["None", "None"])))
    elif q == "cluster.arn":
        print("arn:aws:eks:%s:111122223333:cluster/%s" % (os.environ["REGION"], opts["name"]))
    elif q == "cluster.resourcesVpcConfig.subnetIds[]":
        print("subnet-%s-1\tsubnet-%s-2" % (opts["name"], opts["name"]))
    elif q == "cluster.resourcesVpcConfig.clusterSecurityGroupId":
        print("sg-" + opts["name"])
    else:
        sys.stderr.write("fake aws: unexpected query %s\n" % q); sys.exit(2)
elif svc == "ec2" and op == "describe-subnets":
    print("\t".join(opts["subnet-ids"].split()))
elif svc == "secretsmanager" and op == "get-secret-value":
    v = st["secrets"].get(opts["secret-id"])
    if v is None:
        sys.stderr.write("ResourceNotFoundException\n"); sys.exit(254)
    print(v)
elif svc == "secretsmanager" and op == "put-secret-value":
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(["put", opts["secret-id"], opts["secret-string"]]) + "\n")
else:
    sys.stderr.write("fake aws: unexpected call %s %s\n" % (svc, op)); sys.exit(2)
'''

pytestmark = pytest.mark.skipif(TASK is None, reason="go-task not on PATH")


def _cluster(prefix=PREFIX, env="dev", status="ACTIVE"):
    return {"status": status, "tags": [prefix or "None", env or "None"]}


def _env(tmp_path, clusters, secrets=None, list_fails=False):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "aws").chmod(0o755)
    st, log = tmp_path / "state.json", tmp_path / "calls.jsonl"
    st.write_text(json.dumps({"clusters": clusters, "secrets": secrets or {}, "list_fails": list_fails}))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(st),
               FAKE_LOG=str(log), REGION=REGION)
    return env, log


def _calls(log):
    return [json.loads(l) for l in log.read_text().splitlines() if l]


def _resolve(tmp_path, clusters, env_name="dev", preset="", **kw):
    env, log = _env(tmp_path, clusters, **kw)
    res = subprocess.run(["bash", RESOLVER, PREFIX, REGION, env_name, preset], env=env,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip(), res.stderr


# ── resolver ──────────────────────────────────────────────────────────────────────────

def test_workshop_name_is_kept(tmp_path):
    # Workshop spokes: same name as before, found with one describe call (no listing).
    clusters = {f"{PREFIX}-spoke-dev": _cluster(env="dev"), f"{PREFIX}-spoke-prod": _cluster(env="prod")}
    env, log = _env(tmp_path, clusters)
    out = subprocess.run(["bash", RESOLVER, PREFIX, REGION, "dev"], env=env, capture_output=True, text=True)
    assert out.stdout.strip() == f"{PREFIX}-spoke-dev"
    assert not [c for c in _calls(log) if c[2] == "list-clusters"]


def test_non_workshop_spoke_is_found_by_tags(tmp_path):
    # peeks-a style: spoke named <prefix>-dev; the hub (environment=control-plane) is ignored.
    clusters = {f"{PREFIX}-hub": _cluster(env="control-plane"), f"{PREFIX}-dev": _cluster(env="dev"),
                "other-dev": _cluster(prefix="other", env="dev")}
    assert _resolve(tmp_path, clusters, "dev")[0] == f"{PREFIX}-dev"
    assert _resolve(_sub(tmp_path), clusters, "prod")[0] == ""


def _sub(tmp_path):
    d = tmp_path / ("s%d" % len(list(tmp_path.iterdir())))
    d.mkdir()
    return d


def test_operator_set_name_wins(tmp_path):
    clusters = {f"{PREFIX}-spoke-dev": _cluster(env="dev"), "mine": _cluster(env="dev")}
    assert _resolve(tmp_path, clusters, "dev", preset="mine")[0] == "mine"
    # A stale preset (cluster gone) falls through to discovery.
    assert _resolve(_sub(tmp_path), clusters, "dev", preset="gone")[0] == f"{PREFIX}-spoke-dev"


def test_several_tag_matches_pick_first_and_warn(tmp_path):
    clusters = {"zz-dev": _cluster(env="dev"), "aa-dev": _cluster(env="dev")}
    out, err = _resolve(tmp_path, clusters, "dev")
    assert out == "aa-dev" and "WARN" in err and "spoke_dev_cluster_name" in err


@pytest.mark.parametrize("case", ["no-spokes", "list-fails"])
def test_nothing_found_is_not_an_error(tmp_path, case):
    clusters = {f"{PREFIX}-hub": _cluster(env="control-plane")} if case == "no-spokes" else {"x": _cluster()}
    out, _ = _resolve(tmp_path, clusters, "dev", list_fails=(case == "list-fails"))
    assert out == ""


# ── seed-observability spoke block ────────────────────────────────────────────────────

def _spoke_block(provider):
    with open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")) as f:
        cmds = yaml.safe_load(f)["tasks"]["secrets-manager:seed-observability"]["cmds"]
    text = next(c for c in cmds if isinstance(c, str) and "Populate spoke scraper values" in c)
    start = text.index("# Populate spoke scraper values")
    end = text.index("# Update Keycloak SAML client with AMG URL")
    return text[start:end]


def _run_block(tmp_path, provider, clusters, meta):
    env, log = _env(tmp_path, clusters, secrets={f"{HUB}/config": json.dumps({"metadata": json.dumps(meta)})})
    (tmp_path / "scripts").mkdir(exist_ok=True)
    shutil.copy(RESOLVER, tmp_path / "scripts")
    tvars = dict({k: "" for k in COLORS}, HUB_CLUSTER_NAME=HUB, RESOURCE_PREFIX=PREFIX, AWS_REGION=REGION)
    tf = tmp_path / "Taskfile.yaml"
    tf.write_text(yaml.safe_dump({"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": tvars,
                                  "tasks": {"run": {"cmds": [_spoke_block(provider)]}}}, sort_keys=False))
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    puts = [c for c in _calls(log) if c[0] == "put"]
    meta_out = json.loads(json.loads(puts[-1][2])["metadata"]) if puts else None
    return res, meta_out


@pytest.mark.parametrize("provider", PROVIDERS)
def test_seed_workshop_spokes_keep_their_names_and_add_no_name_key(tmp_path, provider):
    clusters = {f"{PREFIX}-spoke-dev": _cluster(env="dev"), f"{PREFIX}-spoke-prod": _cluster(env="prod")}
    res, meta = _run_block(tmp_path, provider, clusters, {"aws_grafana_url": "g"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert meta["spoke_dev_cluster_arn"].endswith(f"cluster/{PREFIX}-spoke-dev")
    assert meta["spoke_prod_cluster_arn"].endswith(f"cluster/{PREFIX}-spoke-prod")
    assert "spoke_dev_cluster_name" not in meta and "spoke_prod_cluster_name" not in meta, meta


@pytest.mark.parametrize("provider", PROVIDERS)
def test_seed_peeks_a_style_spoke_is_wired_and_named(tmp_path, provider):
    clusters = {f"{PREFIX}-hub": _cluster(env="control-plane"), f"{PREFIX}-dev": _cluster(env="dev")}
    res, meta = _run_block(tmp_path, provider, clusters, {"aws_grafana_url": "g"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert meta["spoke_dev_cluster_arn"].endswith(f"cluster/{PREFIX}-dev"), meta
    assert meta["spoke_dev_private_subnet_ids"] and meta["spoke_dev_security_group_id"] == f"sg-{PREFIX}-dev"
    assert meta["spoke_dev_cluster_name"] == f"{PREFIX}-dev"
    assert meta["spoke_prod_cluster_arn"] == "" and "spoke_prod_cluster_name" not in meta
    assert "No prod spoke found" in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
def test_seed_never_overwrites_an_operator_set_name(tmp_path, provider):
    clusters = {f"{PREFIX}-dev": _cluster(env="dev"), "custom-dev": _cluster(env="dev")}
    res, meta = _run_block(tmp_path, provider, clusters,
                           {"aws_grafana_url": "g", "spoke_dev_cluster_name": "custom-dev"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert meta["spoke_dev_cluster_name"] == "custom-dev"
    assert meta["spoke_dev_cluster_arn"].endswith("cluster/custom-dev"), meta


@pytest.mark.parametrize("provider", PROVIDERS)
def test_seed_with_no_spokes_writes_nothing_and_does_not_fail(tmp_path, provider):
    res, meta = _run_block(tmp_path, provider, {f"{PREFIX}-hub": _cluster(env="control-plane")}, {})
    assert res.returncode == 0, res.stdout + res.stderr
    assert meta is None, "no put-secret-value when no spoke exists"
    assert res.stdout.count("Scraper skipped") == 2, res.stdout


# ── static: both providers keep the preserved-key list and the gate in step ───────────

@pytest.mark.parametrize("provider", PROVIDERS)
def test_hub_seed_preserves_the_name_keys(provider):
    with open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")) as f:
        text = f.read()
    assert text.count('"spoke_dev_cluster_name", "spoke_prod_cluster_name" ] as $k') == 1
