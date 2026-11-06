"""Hermetic test for workshop `destroy` Phase 1 (drain) with Argo CD self-heal: the drain
denies automated syncs to each spoke (AppProject sync window) before deleting its load
balancers, then waits (bounded) until no load balancer is left in the spoke's VPC.

Live case: the drain deleted the spoke's LoadBalancer Services and Ingresses, the hub's
Argo CD re-applied them within seconds (selfHeal), the spoke's LB controller re-created the
NLB/ALB, and once the cluster was deleted those LBs blocked the spoke subnets/VPC delete
(95 DeleteSubnet DependencyViolation; the sweep removed them much later).

The Phase 1 cmd is read verbatim from workshop/Taskfile.yaml and run under go-task with the
Taskfile's `set:` options. kubectl, aws and sleep are fakes on PATH sharing one state file:
a Service deleted on the spoke is re-created by "Argo CD" unless an AppProject carries a
deny window for that spoke, and the spoke VPC holds a load balancer while the Service exists.

Run:  python -m pytest workshop/scripts/tests/test_destroy_drain_sync_window.py -q
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

COMMON = r'''
import fcntl, json, os, sys
STATE = os.environ["FAKE_STATE"]
_L = open(STATE + ".lock", "a"); fcntl.flock(_L, fcntl.LOCK_EX)
st = json.load(open(STATE))
def save():
    json.dump(st, open(STATE, "w"))
def denied(c):
    return any(w.get("kind") == "deny" and c in (w.get("clusters") or [])
               for p in st["projects"].values() for w in p.get("syncWindows", []))
def self_heal():
    # Argo CD automated sync with selfHeal: a drained Service comes back unless denied.
    if not st["svc"] and not denied(os.environ["FAKE_SPOKE"]):
        st["svc"] = True; st["recreated"] += 1
'''

FAKE_KUBECTL = "#!{python} -I\n" + COMMON + r'''
a = sys.argv[1:]
kc = a[a.index("--kubeconfig") + 1] if "--kubeconfig" in a else ""
a = [x for i, x in enumerate(a) if x != "--kubeconfig" and (i == 0 or a[i - 1] != "--kubeconfig")]
hub = kc == os.environ["FAKE_HUB_KC"]
verb = a[0]
rc = 0
if hub and verb == "get" and a[1].startswith("appprojects"):
    print("\n".join("appproject.argoproj.io/" + n for n in st["projects"]))
elif hub and verb == "get" and a[1].startswith("appproject"):
    print(json.dumps({"spec": st["projects"][a[1].split("/", 1)[1]]}))
elif hub and verb == "patch":
    p = st["projects"][a[1].split("/", 1)[1]]
    body = json.loads(a[a.index("-p") + 1])
    t = a[a.index("--type") + 1]
    if t == "json":
        if "syncWindows" not in p:
            rc = 1  # JSON-patch add to /spec/syncWindows/- fails when the list is absent
        else:
            p["syncWindows"].append(body[0]["value"])
    else:
        p["syncWindows"] = body["spec"]["syncWindows"]
elif not hub and verb == "get" and a[1] == "svc":
    items = [{"metadata": {"namespace": "agentgateway", "name": "proxy"}, "spec": {"type": "LoadBalancer"}}] if st["svc"] else []
    print(json.dumps({"items": items}))
elif not hub and verb == "delete" and a[1] == "svc":
    st["svc"] = False
    self_heal()
save(); sys.exit(rc)
'''

FAKE_AWS = "#!{python} -I\n" + COMMON + r'''
a = sys.argv[1:]
if a[:2] == ["eks", "list-clusters"]:
    print(os.environ["FAKE_SPOKE"])
elif a[:2] == ["eks", "update-kubeconfig"]:
    kc = a[a.index("--kubeconfig") + 1]
    open(kc, "w").write("spoke\n")
elif a[:2] == ["eks", "describe-cluster"]:
    print("vpc-spoke")
elif a[:2] == ["elbv2", "describe-load-balancers"]:
    self_heal()
    print(1 if st["svc"] else 0)
save(); sys.exit(0)
'''

FAKE_SLEEP = '''#!/bin/sh
echo "$1" >> "$FAKE_CLOCK"
'''


def _phase1(src):
    for c in src["tasks"]["destroy"]["cmds"]:
        t = c.get("cmd", "") if isinstance(c, dict) else (c if isinstance(c, str) else "")
        if "Phase 1 — draining" in t:
            return t
    raise AssertionError("Phase 1 cmd not found")


def _run(tmp):
    if not TASK:
        pytest.skip("go-task not on PATH")
    with open(TASKFILE) as f:
        src = yaml.safe_load(f)
    bindir = tmp / "bin"
    bindir.mkdir()
    for name, body in (("kubectl", FAKE_KUBECTL), ("aws", FAKE_AWS), ("sleep", FAKE_SLEEP)):
        (bindir / name).write_text(body.replace("{python}", sys.executable))
        (bindir / name).chmod(0o755)
    state, clock = tmp / "state.json", tmp / "clock"
    # "default" has no syncWindows (Argo CD default project), "spoke-workloads" has one.
    state.write_text(json.dumps({"svc": True, "recreated": 0, "projects": {
        "default": {}, "spoke-workloads": {"syncWindows": [{"kind": "allow", "schedule": "* * * * *", "duration": "1h"}]}}}))
    clock.write_text("")
    (tmp / "config.yaml").write_text("resourcePrefix: acme\naws:\n  region: eu-west-3\n")
    hub_kc = tmp / "hub-kubeconfig"
    hub_kc.write_text("hub\n")
    gvars = {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")}
    gvars.update({"CONFIG_FILE": str(tmp / "config.yaml"), "HUB_KUBECONFIG": str(hub_kc),
                  "AWS_REGION": "eu-west-3", "RESOURCE_PREFIX": "acme"})
    tf = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": gvars,
          "tasks": {"run": {"cmds": [_phase1(src)]}}}
    (tmp / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(state),
               FAKE_CLOCK=str(clock), FAKE_SPOKE=SPOKE, FAKE_HUB_KC=str(hub_kc))
    res = subprocess.run([TASK, "-s", "run"], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    waited = sum(int(x) for x in clock.read_text().split() if x.isdigit())
    return res, json.loads(state.read_text()), waited


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("drain"))


def test_exit_code(run):
    assert run[0].returncode == 0, run[0].stdout + run[0].stderr


def test_every_project_denies_syncs_to_the_spoke(run):
    _res, st, _w = run
    for name, p in st["projects"].items():
        deny = [w for w in p.get("syncWindows", []) if w["kind"] == "deny" and SPOKE in w.get("clusters", [])]
        assert len(deny) == 1, (name, p)
        assert deny[0]["manualSync"] is False
    # the existing window is kept
    assert any(w["kind"] == "allow" for w in st["projects"]["spoke-workloads"]["syncWindows"])


def test_no_load_balancer_left_after_the_drain(run):
    _res, st, waited = run
    assert st["svc"] is False and st["recreated"] == 0, st
    assert waited < 60, f"{waited}s of gate polling"
