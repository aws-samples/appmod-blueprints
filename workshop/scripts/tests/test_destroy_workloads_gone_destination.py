"""Hermetic tests for kind-kro-ack `hub:destroy-addons` step 5: a workload Application whose
destination cluster is already gone has its finalizer dropped at once instead of waiting out
`kubectl delete --timeout=300s`.

On a workshop teardown the caller deletes the spokes before the hub (workshop destroy Phase
2), so in Phase 3 agents-dev-cd / agents-prod-cd still point at peeks-spoke-dev /
peeks-spoke-prod. Their resources-finalizer can never complete; each waited 300 s (10 min of
a 40 min budget). A destination counts as gone only on positive evidence: no Argo CD cluster
Secret names it, or the EKS cluster its Secret names is not found. When the cluster Secrets
cannot be read, every destination counts as live (the old behaviour).

The cmd is read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and run under
go-task with the Taskfile's `set:` options. `kubectl` and `aws` are fakes on PATH; a stuck
finalizer is modelled by a `delete --timeout=...` that sleeps FAKE_DELAY then fails.

Run:  python -m pytest workshop/scripts/tests/test_destroy_workloads_gone_destination.py -q
Set DESTROY_ADDONS_TASKFILE=<path> to run the same checks against another Taskfile.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.environ.get("DESTROY_ADDONS_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
DELAY = 2.0  # stands for the 300 s a stuck resources-finalizer costs

FAKE_KUBECTL = r'''#!{python} -I
import base64, fcntl, json, os, sys, time
STATE, LOG = os.environ["FAKE_STATE"], os.environ["FAKE_LOG"]
_LOCK = open(STATE + ".lock", "a"); fcntl.flock(_LOCK, fcntl.LOCK_EX)
st = json.load(open(STATE))
args = sys.argv[1:]
def log(*ev):
    with open(LOG, "a") as f:
        f.write(json.dumps(ev) + "\n")
def save():
    json.dump(st, open(STATE, "w"))
pos = [a for i, a in enumerate(args) if not a.startswith("-")
       and not (i and args[i - 1] in ("-n", "-o", "-p", "--type", "-l"))]
verb, kind = pos[0], pos[1]
name = pos[2] if len(pos) > 2 else None
if verb == "get" and kind == "secrets":
    if os.environ.get("FAKE_SECRETS_FAIL"):
        sys.stderr.write("Error from server (Forbidden)\n"); sys.exit(1)
    b = lambda s: base64.b64encode(s.encode()).decode()
    items = []
    for s in st["secrets"]:
        md = {"name": s["name"], "labels": {"argocd.argoproj.io/secret-type": "cluster"}}
        if s.get("aws"):
            md["labels"]["aws_cluster_name"] = s["aws"]
        items.append({"metadata": md, "data": {"name": b(s["name"]), "server": b(s["server"])}})
    print(json.dumps({"items": items})); sys.exit(0)
if verb == "get" and kind == "applications":
    for n, a in st["apps"].items():
        print(f"{n} {a['project']} {a.get('dname', '')}|{a.get('dserver', '')}")
    sys.exit(0)
if verb == "patch" and kind == "application":
    if name in st["apps"]:
        st["apps"][name]["finalizers"] = []
        log("strip", name); save()
    sys.exit(0)
if verb == "delete" and kind == "application":
    a = st["apps"].get(name)
    if a is None:
        sys.exit(1)
    if a.get("finalizers") and a.get("stuck"):
        to = [x for x in args if x.startswith("--timeout=")]
        log("wait", name, to[0] if to else "")
        fcntl.flock(_LOCK, fcntl.LOCK_UN)
        if to:
            time.sleep(float(os.environ["FAKE_DELAY"]))
            sys.exit(1)
        sys.exit(0)  # --wait=false: deletion pending forever
    del st["apps"][name]
    log("deleted", name, "finalizer-dropped" if a.get("stuck") else "cascade"); save()
    sys.exit(0)
sys.exit(0)
'''

FAKE_AWS = r'''#!{python} -I
import json, os, sys
live = json.loads(os.environ["FAKE_EKS_LIVE"])
args = sys.argv[1:]
if args[:2] == ["eks", "describe-cluster"]:
    n = args[args.index("--name") + 1]
    if n in live:
        print("ACTIVE"); sys.exit(0)
    sys.stderr.write("An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation: No cluster found for name: %s.\n" % n)
    sys.exit(254)
sys.exit(0)
'''

FIN = ["resources-finalizer.argocd.argoproj.io"]


def _state():
    return {
        "secrets": [
            {"name": "peeks-hub", "server": "arn:aws:eks:region:acct:cluster/peeks-hub", "aws": "peeks-hub"},
            # kro has not removed it yet, but the EKS cluster is gone
            {"name": "peeks-spoke-prod", "server": "https://spoke-prod.example", "aws": "peeks-spoke-prod"},
        ],
        "apps": {
            # peeks-spoke-dev: no cluster Secret any more
            "agents-dev-cd": {"project": "spoke-workloads", "dname": "peeks-spoke-dev",
                              "finalizers": FIN, "stuck": True},
            # peeks-spoke-prod: Secret still there, EKS cluster not found
            "agents-prod-cd": {"project": "spoke-workloads", "dname": "peeks-spoke-prod",
                               "finalizers": FIN, "stuck": True},
            # live destinations: normal cascade delete
            "rust-app": {"project": "rust-project", "dname": "peeks-hub", "finalizers": FIN},
            "local-app": {"project": "java-project", "dserver": "https://kubernetes.default.svc",
                          "finalizers": FIN},
            # addon / platform projects are not step 5's business
            "cert-manager-peeks-hub": {"project": "default", "dname": "peeks-hub", "finalizers": FIN},
        },
    }


def _step5():
    with open(TASKFILE) as f:
        task = yaml.safe_load(f)["tasks"]["hub:destroy-addons"]
    text = lambda c: c.get("cmd", "") if isinstance(c, dict) else c
    cmd = next(c for c in task["cmds"] if "Deleting workload" in text(c))
    return task["vars"], cmd


def _run(tmp, extra_env=None):
    if not TASK:
        pytest.skip("go-task not on PATH")
    tvars, cmd = _step5()
    tvars = dict(tvars, AWS_REGION="eu-west-3")
    bindir = tmp / "bin"
    bindir.mkdir()
    (bindir / "kubectl").write_text(FAKE_KUBECTL.replace("{python}", sys.executable))
    (bindir / "aws").write_text(FAKE_AWS.replace("{python}", sys.executable))
    for f in ("kubectl", "aws"):
        (bindir / f).chmod(0o755)
    state, log = tmp / "state.json", tmp / "log.jsonl"
    state.write_text(json.dumps(_state()))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_DELAY=str(DELAY),
               FAKE_STATE=str(state), FAKE_LOG=str(log), FAKE_EKS_LIVE=json.dumps(["peeks-hub"]))
    env.update(extra_env or {})
    tf = tmp / "Taskfile.yml"
    tf.write_text(yaml.safe_dump({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "vars": {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")},
        "tasks": {"run": {"vars": tvars, "cmds": [cmd]}}}, sort_keys=False))
    t0 = time.time()
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp, env=env,
                         capture_output=True, text=True, timeout=120)
    elapsed = time.time() - t0
    events = [json.loads(line) for line in log.read_text().splitlines()]
    return res, elapsed, events, json.loads(state.read_text())


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("step5"))


def test_exit_code(run):
    assert run[0].returncode == 0, run[0].stdout + run[0].stderr


def test_gone_destinations_do_not_wait(run):
    _res, elapsed, events, st = run
    waits = [e for e in events if e[0] == "wait" and e[2]]
    assert waits == [], f"waited on a finalizer that can never complete: {waits}"
    assert elapsed < DELAY, f"{elapsed:.1f}s"
    for app in ("agents-dev-cd", "agents-prod-cd"):
        assert ["deleted", app, "finalizer-dropped"] in events, events
        assert app not in st["apps"]


def test_live_destinations_keep_the_cascade(run):
    _res, _elapsed, events, st = run
    for app in ("rust-app", "local-app"):
        assert ["deleted", app, "cascade"] in events, events
        assert ["strip", app] not in events, f"{app}: finalizer stripped on a live destination"
    assert "cert-manager-peeks-hub" in st["apps"], "step 5 touched an addon Application"


def test_unreadable_cluster_secrets_count_as_live(tmp_path):
    res, elapsed, events, st = _run(tmp_path, {"FAKE_SECRETS_FAIL": "1"})
    assert res.returncode == 0, res.stdout + res.stderr
    waits = sorted(e[1] for e in events if e[0] == "wait" and e[2])
    assert waits == ["agents-dev-cd", "agents-prod-cd"], events
    assert elapsed >= 2 * DELAY
    # still removed, by the old timeout fallback
    assert "agents-dev-cd" not in st["apps"] and "agents-prod-cd" not in st["apps"]
