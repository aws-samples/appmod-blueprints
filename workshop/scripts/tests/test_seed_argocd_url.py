"""Hermetic tests for kind-kro-ack `secrets-manager:seed-argocd-url`: on a fresh install
`aws_argocd_url` in <hub>/config is filled from the Argo CD capability once it exists.

`secrets-manager:seed` resolves the capability URL as well, but on a fresh install it runs
before the capability is created and stores "". `hub:seed` now calls this task after
`hub:apply-root-appset` (which waits for the capability's CRDs). It must fill only an empty
value, merge only that key, and never fail the install.

The task's cmds are read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and run
under go-task's own interpreter with the Taskfile's `set:` options (bash with
`set -euo pipefail` if go-task is not on PATH). `aws` and `sleep` are fakes on PATH. No AWS,
no network.

Run:  python -m pytest workshop/scripts/tests/test_seed_argocd_url.py -q
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

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.environ.get("SEED_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
TASK_NAME = "secrets-manager:seed-argocd-url"
HUB, REGION = "acme-hub", "us-west-2"
HOST = "argocd-0123abcd.eks-capabilities.us-west-2.amazonaws.com"
COLORS = ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP", "C_WARN")

FAKE_AWS = r'''#!{python} -I
import json, os, sys
st_path, log = os.environ["FAKE_AWS_STATE"], os.environ["FAKE_AWS_LOG"]
st = json.load(open(st_path))
svc, op, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
opts, i = {}, 0
while i < len(rest):
    if rest[i].startswith("--") and i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        opts[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        i += 1
with open(log, "a") as f:
    f.write(json.dumps([svc, op, {k: v for k, v in opts.items() if k != "secret-string"}]) + "\n")
rc = 0
if (svc, op) == ("secretsmanager", "get-secret-value"):
    if st["secret"] is None:
        sys.stderr.write("An error occurred (ResourceNotFoundException) when calling the GetSecretValue operation\n")
        rc = 254
    else:
        print(st["secret"])
elif (svc, op) == ("eks", "describe-capability"):
    st["describes"] += 1
    if st["ready_after"] is not None and st["describes"] >= st["ready_after"]:
        print("https://" + st["host"])
    elif st["ready_after"] is None:
        sys.stderr.write("An error occurred (ResourceNotFoundException) when calling the DescribeCapability operation\n")
        rc = 254
    else:
        print("None")
elif (svc, op) == ("secretsmanager", "put-secret-value"):
    if st.get("put_fails"):
        sys.stderr.write("An error occurred (AccessDeniedException) when calling the PutSecretValue operation\n")
        rc = 254
    else:
        st["puts"].append(opts["secret-string"])
        print(json.dumps({"VersionId": "v2"}))
json.dump(st, open(st_path, "w"))
sys.exit(rc)
'''
FAKE_SLEEP = '''#!/bin/sh
printf '["sleep", %s]\\n' "$1" >> "$FAKE_AWS_LOG"
'''


def _secret(argocd_url):
    """A <hub>/config secret as hub:seed writes it, plus keys other tasks merge in later."""
    meta = {"addonsRepoURL": "https://example.com/acme/appmod-blueprints", "aws_region": REGION,
            "aws_cluster_name": HUB, "ingress_domain_name": "d111111abcdef8.cloudfront.net",
            "git_token": "not-a-real-token", "aws_argocd_url": argocd_url,
            "overlay_repo_url": "https://git.example.com/user1/fleet-config.git",
            "aws_grafana_url": "g-0123.grafana-workspace.us-west-2.amazonaws.com"}
    return json.dumps({"metadata": json.dumps(meta, separators=(",", ":")),
                       "config": '{"tlsClientConfig":{"insecure":false}}',
                       "server": f"arn:aws:eks:{REGION}:111122223333:cluster/{HUB}",
                       "addons": '{"provider":"kro-ack"}', "vpc": '{"id":"vpc-0"}'}, indent=2)


def _task(name):
    with open(TASKFILE) as f:
        return yaml.safe_load(f)["tasks"][name]


def _run(tmp_path, secret, ready_after=1, put_fails=False):
    try:
        cmds = _task(TASK_NAME)["cmds"]
    except KeyError:
        pytest.fail(f"no task {TASK_NAME} in {TASKFILE}")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    (bindir / "sleep").write_text(FAKE_SLEEP)
    for f in ("aws", "sleep"):
        (bindir / f).chmod(0o755)
    state, log = tmp_path / "state.json", tmp_path / "aws.jsonl"
    state.write_text(json.dumps({"secret": secret, "host": HOST, "ready_after": ready_after,
                                 "describes": 0, "puts": [], "put_fails": put_fails}))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_AWS_STATE=str(state), FAKE_AWS_LOG=str(log))
    tvars = {"HUB_CLUSTER_NAME": HUB, "AWS_REGION": REGION}
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
    return res, json.loads(state.read_text())


def _meta(secret_string):
    return json.loads(json.loads(secret_string)["metadata"])


def test_hub_seed_fills_the_url_after_the_capability_crds(tmp_path):
    names = [c.get("task") for c in _task("hub:seed")["cmds"] if isinstance(c, dict)]
    assert TASK_NAME in names, f"hub:seed never calls {TASK_NAME}: {names}"
    assert names.index(TASK_NAME) > names.index("hub:apply-root-appset"), names


def test_empty_url_is_filled_from_the_capability(tmp_path):
    before = _secret("")
    res, st = _run(tmp_path, before, ready_after=3)
    assert res.returncode == 0, res.stdout + res.stderr
    assert len(st["puts"]) == 1, res.stdout
    after = json.loads(st["puts"][0])
    assert _meta(st["puts"][0])["aws_argocd_url"] == HOST
    # Only that key changes: every other metadata key and every top-level key is kept.
    old, new = json.loads(before), after
    assert {k: v for k, v in new.items() if k != "metadata"} == {k: v for k, v in old.items() if k != "metadata"}
    assert dict(_meta(before), aws_argocd_url=HOST) == _meta(st["puts"][0])


def test_a_set_url_is_left_alone(tmp_path):
    res, st = _run(tmp_path, _secret("argocd-existing.example.com"))
    assert res.returncode == 0, res.stdout + res.stderr
    assert st["puts"] == [] and st["describes"] == 0, res.stdout


def test_no_capability_is_not_fatal(tmp_path):
    res, st = _run(tmp_path, _secret(""), ready_after=None)
    assert res.returncode == 0, res.stdout + res.stderr
    assert st["puts"] == [], res.stdout
    assert "stays empty" in res.stdout, res.stdout


def test_unreadable_secret_is_not_fatal(tmp_path):
    res, st = _run(tmp_path, None)
    assert res.returncode == 0, res.stdout + res.stderr
    assert st["puts"] == [], res.stdout


def test_failed_write_is_not_fatal(tmp_path):
    res, st = _run(tmp_path, _secret(""), put_fails=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "stays empty" in res.stdout, res.stdout


def test_the_secret_is_never_printed(tmp_path):
    res, _ = _run(tmp_path, _secret(""))
    assert "not-a-real-token" not in res.stdout + res.stderr
