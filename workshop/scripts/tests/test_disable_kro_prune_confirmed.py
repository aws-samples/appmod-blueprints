"""Hermetic tests for workshop `spokes:disable-kro` / `spokes:disable-all` (destroy Phase 2):
a spoke is de-registered from Argo CD only once its kro EksclusterWithVpc is really being
deleted, and a spoke whose deletion never started fails loud instead of being waited for.

Live case: `argocd app sync --prune` failed with Unauthenticated, the kubectl `.operation`
patch was accepted (PRUNED=true) but deleted nothing, the spoke's EksclusterWithVpc never got
a deletionTimestamp, the clusters-kro-<spoke> Application and the cluster Secret were then
deleted (the cluster orphaned, still ACTIVE), and Phase 2 waited out its full 30 minutes.

The two cmds are read verbatim from workshop/Taskfile.yaml and run under go-task with the
Taskfile's `set:` options. git, kubectl, aws, argocd and sleep are fakes on PATH; `sleep`
only adds its argument to a virtual clock, so the 30 min wait costs nothing to run.

Run:  python -m pytest workshop/scripts/tests/test_disable_kro_prune_confirmed.py -q
Set WORKSHOP_TASKFILE=<path> to run the same checks against another Taskfile.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.environ.get("WORKSHOP_TASKFILE") or os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")
SPOKE = "acme-spoke-dev"

FAKE_KUBECTL = r'''#!{python} -I
import fcntl, json, os, sys
STATE, LOG = os.environ["FAKE_STATE"], os.environ["FAKE_LOG"]
_L = open(STATE + ".lock", "a"); fcntl.flock(_L, fcntl.LOCK_EX)
st = json.load(open(STATE))
a = sys.argv[1:]
if a and a[0] == "--kubeconfig":
    a = a[2:]
def log(*e):
    open(LOG, "a").write(json.dumps(list(e)) + "\n")
def save():
    json.dump(st, open(STATE, "w"))
verb = a[0]
if verb == "get" and a[1] == "crd":
    sys.exit(0)
if verb == "get" and a[1].startswith("eksclusterwithvpcs"):
    if st["cr"] == "gone":
        sys.stderr.write('Error from server (NotFound): eksclusterwithvpcs "x" not found\n'); sys.exit(1)
    md = {"name": a[2]}
    if st["cr"] == "deleting":
        md["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    print(json.dumps({"metadata": md})); sys.exit(0)
if verb == "get" and a[1] == "application":
    print(json.dumps({"spec": {"syncPolicy": {}}})); sys.exit(0)
if verb == "get" and a[1].startswith("applicationsets"):
    sys.exit(0)  # refresh annotation already consumed
if verb == "patch" and a[1] == "application":
    log("operation-patch", st["cr"])
    if os.environ.get("FAKE_PRUNE_WORKS") and st["cr"] == "live":
        st["cr"] = "deleting"
    save(); sys.exit(0)
if verb == "delete" and a[1].startswith("eksclusterwithvpcs"):
    log("delete-cr", st["cr"])
    if os.environ.get("FAKE_DIRECT_DELETE_WORKS") and st["cr"] == "live":
        st["cr"] = "deleting"
    save(); sys.exit(0)
if verb == "delete" and a[1].startswith("applications"):
    log("delete-app", st["cr"], *[x for x in a[2:] if not x.startswith("-") and x != "argocd"])
    sys.exit(0)
if verb == "delete" and a[1] == "secret":
    log("delete-cluster-secret", st["cr"]); sys.exit(0)
sys.exit(0)
'''

FAKE_GIT = r'''#!/bin/sh
case "$1" in
  clone)
    d="$3"; mkdir -p "$d/.git" "$d/gitops/fleet/spoke-values/tenants/workshop/kro-clusters/clusters"
    cat > "$d/gitops/fleet/spoke-values/tenants/workshop/kro-clusters/values.yaml" <<EOF
clusters:
  $FAKE_SPOKE:
    region: eu-west-3
EOF
    echo '{}' > "$d/gitops/fleet/spoke-values/tenants/workshop/kro-clusters/clusters/$FAKE_SPOKE.json" ;;
esac
exit 0
'''

FAKE_ARGOCD = r'''#!/bin/sh
case "$1 $2" in
  "account get-user-info") echo '{"loggedIn": false}' ;;
  "app sync") echo 'rpc error: code = Unauthenticated desc = invalid session' >&2; exit 20 ;;
  "app get") echo 'rpc error: code = Unauthenticated' >&2; exit 20 ;;
esac
exit 0
'''

FAKE_AWS = r'''#!/bin/sh
# describe-cluster: the spoke stays ACTIVE unless its CR is being deleted (state file).
if [ "$1 $2" = "eks describe-cluster" ]; then
  grep -q '"cr": "live"' "$FAKE_STATE" && exit 0
  echo "ResourceNotFoundException" >&2; exit 254
fi
exit 0
'''

FAKE_SLEEP = '''#!/bin/sh
echo "$1" >> "$FAKE_CLOCK"
'''


def _cmd(task, name):
    c = task["tasks"][name]["cmds"][0]
    return c.get("cmd") if isinstance(c, dict) else c


def _run(tmp, env_extra, which="spokes:disable-kro"):
    if not TASK:
        pytest.skip("go-task not on PATH")
    with open(TASKFILE) as f:
        src = yaml.safe_load(f)
    bindir = tmp / "bin"
    bindir.mkdir()
    for name, body in (("kubectl", FAKE_KUBECTL.replace("{python}", sys.executable)), ("git", FAKE_GIT),
                       ("argocd", FAKE_ARGOCD), ("aws", FAKE_AWS), ("sleep", FAKE_SLEEP)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    state, log, clock = tmp / "state.json", tmp / "log.jsonl", tmp / "clock"
    state.write_text(json.dumps({"cr": "live"}))
    log.write_text("")
    clock.write_text("")
    (tmp / "private").mkdir()
    gvars = {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")}
    gvars.update({"GIT_USERNAME": "user1", "GIT_PASSWORD": "pw", "GIT_DOMAIN": "git.example",
                  "REPO": str(tmp), "HUB_CLUSTER_NAME": "acme-hub", "AWS_REGION": "eu-west-3",
                  "RESOURCE_PREFIX": "acme", "CONFIG_FILE": str(tmp / "config.yaml")})
    tf = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": gvars, "tasks": {
        "spokes:disable-kro": {"vars": {"CLUSTER": "{{.CLI_ARGS}}"},
                               "cmds": [_cmd(src, "spokes:disable-kro")]},
        "spokes:disable-all": {"cmds": [_cmd(src, "spokes:disable-all")]},
    }}
    (tmp / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(state),
               FAKE_LOG=str(log), FAKE_CLOCK=str(clock), FAKE_SPOKE=SPOKE, **env_extra)
    args = [TASK, "-s", which] + (["--", SPOKE] if which == "spokes:disable-kro" else [])
    res = subprocess.run(args, cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    events = [json.loads(x) for x in log.read_text().splitlines()]
    waited = sum(int(x) for x in clock.read_text().split() if x.isdigit())
    return res, events, waited, json.loads(state.read_text())["cr"]


def _app_deleted_while_live(events):
    return [e for e in events if e[0] in ("delete-app", "delete-cluster-secret") and e[1] == "live"]


def test_prune_that_works_deregisters(tmp_path):
    res, events, _w, cr = _run(tmp_path, {"FAKE_PRUNE_WORKS": "1"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert cr == "deleting"
    assert any(e[0] == "delete-app" for e in events), events
    assert _app_deleted_while_live(events) == []


def test_ineffective_prune_falls_back_to_direct_delete(tmp_path):
    res, events, _w, cr = _run(tmp_path, {"FAKE_DIRECT_DELETE_WORKS": "1"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert cr == "deleting"
    assert ["delete-cr", "live"] in events, events
    assert _app_deleted_while_live(events) == [], "app de-registered while the spoke CR was live"


def test_nothing_deletes_the_spoke_fails_loud_and_keeps_the_app(tmp_path):
    res, events, _w, cr = _run(tmp_path, {})
    assert res.returncode != 0, "disable-kro claimed success while the spoke is not being deleted"
    assert cr == "live"
    assert "is NOT being deleted" in res.stdout + res.stderr
    assert not any(e[0] in ("delete-app", "delete-cluster-secret") for e in events), events


def test_disable_all_does_not_wait_30_min_for_a_spoke_never_deleted(tmp_path):
    res, events, waited, _cr = _run(tmp_path, {}, which="spokes:disable-all")
    assert _app_deleted_while_live(events) == [], events
    assert waited < 600, f"Phase 2 waited {waited}s (virtual) for a spoke whose deletion never started"
    assert "deletion NOT started" in res.stdout + res.stderr, res.stdout
