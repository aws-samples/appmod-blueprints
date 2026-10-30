"""Hermetic tests for kind-kro-ack `secrets-manager:seed`: the opt-in config key
`fleetScopeByPrefix` and the `fleet_scope_by_prefix` metadata key it stamps on <hub>/config.

`fleet_scope_by_prefix: "true"` on the hub cluster-secret (ESO expands <hub>/config metadata
keys 1:1 into annotations) makes gitops/bootstrap/clusters-kro.yaml and fleet-secrets.yaml glob
clusters/<resource_prefix>/*.json and fleet/members/<resource_prefix>/*/values.yaml. The
install-time key lets a hub use that layout from its first render.

Contract:
  - key absent      -> metadata byte-identical to the seed without the feature (no key);
  - true            -> fleet_scope_by_prefix="true" written;
  - false           -> not written;
  - re-seed         -> a value set by hand on <hub>/config is kept, like overlay_repo_*.

The task's cmds are read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and run
under go-task with the Taskfile's `set:` options (bash `set -euo pipefail` if go-task is not on
PATH). `aws` is a fake on PATH, `yq`/`jq` are the real tools. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_seed_fleet_scope_by_prefix.py -q
Set SEED_TASKFILE=<path> to run the same checks against another Taskfile.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
if not (shutil.which("yq") and shutil.which("jq")):
    pytest.skip("yq and jq are required", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.environ.get("SEED_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
TASK_NAME = "secrets-manager:seed"
HUB, REGION = "acme-hub", "us-west-2"
COLORS = ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP", "C_WARN")

FAKE_AWS = r'''#!{python} -I
import json, os, sys
st_path = os.environ["FAKE_AWS_STATE"]
st = json.load(open(st_path))
svc, op, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
opts, i = {}, 0
while i < len(rest):
    if rest[i].startswith("--") and i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        opts[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        i += 1
rc = 0
if (svc, op) == ("secretsmanager", "get-secret-value"):
    if st["secret"] is None:
        sys.stderr.write("An error occurred (ResourceNotFoundException)\n"); rc = 254
    else:
        print(st["secret"])
elif (svc, op) == ("secretsmanager", "restore-secret"):
    rc = 254
elif (svc, op) == ("secretsmanager", "create-secret"):
    if st["secret"] is not None:
        sys.stderr.write("An error occurred (ResourceExistsException)\n"); rc = 254
    else:
        st["writes"].append(opts["secret-string"]); st["secret"] = opts["secret-string"]
elif (svc, op) == ("secretsmanager", "put-secret-value"):
    st["writes"].append(opts["secret-string"]); st["secret"] = opts["secret-string"]
else:
    sys.stderr.write("unexpected aws call %r\n" % sys.argv[1:]); rc = 2
json.dump(st, open(st_path, "w"))
sys.exit(rc)
'''

BASE_CONFIG = {"domain": "d111111abcdef8.cloudfront.net", "platformTags": {}}
TVARS = {"HUB_CLUSTER_NAME": HUB, "AWS_REGION": REGION, "AWS_ACCOUNT_ID": "111122223333",
         "REPO_URL": "https://example.com/acme/appmod-blueprints", "REPO_REVISION": "main",
         "REPO_BASEPATH": "gitops/", "AGENTIC_REPO_URL": "", "AGENTIC_REPO_REVISION": "",
         "FLEET_REPO_URL": "https://example.com/acme/appmod-blueprints", "FLEET_REPO_REVISION": "main",
         "FLEET_REPO_BASEPATH": "gitops/", "CLUSTER_ARN": f"arn:aws:eks:{REGION}:111122223333:cluster/{HUB}",
         "VPC_ID": "vpc-0", "PRIVATE_SUBNET_IDS": "subnet-a,subnet-b", "CLUSTER_SG": "sg-0",
         "INGRESS_SECURITY_GROUPS": "", "RESOURCE_PREFIX": "acme", "INSECURE": "false",
         "INGRESS_CERT_ARN": "", "ADMIN_ROLE_NAME": "Admin", "USER_PASSWORD": "not-a-real-token",
         "ARGOCD_URL": "argocd-0123abcd.example.com"}


def _cmds():
    with open(TASKFILE) as f:
        task = yaml.safe_load(f)["tasks"].get(TASK_NAME)
    if task is None:
        pytest.fail(f"no task {TASK_NAME} in {TASKFILE}")
    return task["cmds"]


def _run(tmp_path, config, existing=None):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "aws").chmod(0o755)
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text(yaml.safe_dump(config))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"secret": existing, "writes": []}))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_STATE=str(state))
    tvars = dict(TVARS, CONFIG_FILE=str(cfg), ROOT_DIR=str(tmp_path))
    cmds = _cmds()
    if TASK:
        tf = tmp_path / "Taskfile.yml"
        tf.write_text(yaml.safe_dump({
            "version": "3", "set": ["errexit", "nounset", "pipefail"],
            "vars": dict({k: "" for k in COLORS}, **tvars),
            "tasks": {"run": {"cmds": cmds}}}, sort_keys=False))
        res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=120)
    else:
        text = "\n".join(c["cmd"] if isinstance(c, dict) else c for c in cmds)
        for k, v in tvars.items():
            text = text.replace("{{.%s}}" % k, v)
        script = tmp_path / "seed.sh"
        script.write_text("set -euo pipefail\n" + re.sub(r"\{\{\.C_[A-Z]+\}\}", "", text))
        res = subprocess.run(["bash", str(script)], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    st = json.loads(state.read_text())
    assert len(st["writes"]) == 1, st
    return st["writes"][0]


def _meta(secret_string):
    return json.loads(json.loads(secret_string)["metadata"])


def test_absent_key_writes_nothing_and_matches_false(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "f").mkdir()
    absent = _run(tmp_path / "a", dict(BASE_CONFIG))
    false = _run(tmp_path / "f", dict(BASE_CONFIG, fleetScopeByPrefix=False))
    assert "fleet_scope_by_prefix" not in _meta(absent)
    # Absent and false are the same seed, byte for byte (the legacy layout).
    assert absent == false


def test_true_stamps_the_key(tmp_path):
    meta = _meta(_run(tmp_path, dict(BASE_CONFIG, fleetScopeByPrefix=True)))
    assert meta["fleet_scope_by_prefix"] == "true"
    assert meta["resource_prefix"] == "acme"


def test_only_that_key_differs_from_the_legacy_seed(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "t").mkdir()
    legacy = _meta(_run(tmp_path / "a", dict(BASE_CONFIG)))
    scoped = _meta(_run(tmp_path / "t", dict(BASE_CONFIG, fleetScopeByPrefix=True)))
    assert dict(legacy, fleet_scope_by_prefix="true") == scoped


def test_false_does_not_write_the_key(tmp_path):
    meta = _meta(_run(tmp_path, dict(BASE_CONFIG, fleetScopeByPrefix=False)))
    assert "fleet_scope_by_prefix" not in meta


def test_reseed_keeps_a_hand_set_value(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    first = _run(tmp_path / "a", dict(BASE_CONFIG))
    meta = _meta(first)
    meta["fleet_scope_by_prefix"] = "true"     # set by hand on <hub>/config
    handset = json.loads(first)
    handset["metadata"] = json.dumps(meta)
    again = _meta(_run(tmp_path / "b", dict(BASE_CONFIG), existing=json.dumps(handset)))
    assert again["fleet_scope_by_prefix"] == "true"


def test_reseed_without_the_key_stays_without_it(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    first = _run(tmp_path / "a", dict(BASE_CONFIG))
    again = _run(tmp_path / "b", dict(BASE_CONFIG), existing=first)
    assert "fleet_scope_by_prefix" not in _meta(again)


def test_only_the_string_true_is_preserved(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    first = _run(tmp_path / "a", dict(BASE_CONFIG))
    meta = dict(_meta(first), fleet_scope_by_prefix="yes")
    stale = json.loads(first)
    stale["metadata"] = json.dumps(meta)
    again = _meta(_run(tmp_path / "b", dict(BASE_CONFIG), existing=json.dumps(stale)))
    assert "fleet_scope_by_prefix" not in again
