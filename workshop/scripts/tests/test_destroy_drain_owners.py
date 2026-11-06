"""Hermetic test for workshop `destroy` Phase 1 (drain) against in-cluster controllers: the
owners of a spoke's Ingresses and LoadBalancer Services are deleted (and waited for) before
the children, so no controller re-creates the load balancer.

Live case (the AppProject deny window was in place, so Argo CD was not the cause): kro
re-created the spoke's Ingress 15 s after the drain deleted it (owner: an AppmodService
instance), and the gateway controller re-created the agentgateway proxy Service (owner: a
Gateway) 30 s after. Their LBs were then orphaned with the spoke VPC.

The Phase 1 cmd is read verbatim from workshop/Taskfile.yaml and run under go-task with the
Taskfile's `set:` options. kubectl, aws and sleep are fakes on PATH sharing one state file:
a controller re-creates a deleted child while its owner exists, deleting an owner removes its
children (garbage collection), an owner may itself be owned (Gateway <- kro instance), and
the spoke VPC holds a load balancer while any Ingress or LoadBalancer Service exists.

Run:  python -m pytest workshop/scripts/tests/test_destroy_drain_owners.py -q
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

FAKE = r'''#!{python} -I
import fcntl, json, os, sys
STATE = os.environ["FAKE_STATE"]
_L = open(STATE + ".lock", "a"); fcntl.flock(_L, fcntl.LOCK_EX)
st = json.load(open(STATE))
def save():
    json.dump(st, open(STATE, "w"))
def key(kind, name, ns):
    return f"{kind}/{ns}/{name}"
def reconcile():
    # owner deleted -> GC its children (transitively)
    changed = True
    while changed:
        changed = False
        for k, o in list(st["objs"].items()):
            ow = o.get("owner")
            if ow and ow not in st["objs"]:
                del st["objs"][k]; changed = True
    # a live owner's controller re-creates a deleted child
    for k, spec in st["templates"].items():
        if k not in st["objs"] and spec["owner"] in st["objs"]:
            st["objs"][k] = dict(spec); st["recreated"].append(k)
def lbs():
    return sum(1 for o in st["objs"].values() if o["kind"] == "Ingress"
               or (o["kind"] == "Service" and o.get("lb")))
def item(k, o):
    kind, ns, name = k.split("/")
    md = {"name": name, "namespace": ns}
    if o.get("owner"):
        okind, ons, oname = o["owner"].split("/")
        g = st["groups"][okind]
        md["ownerReferences"] = [{"apiVersion": f"{g}/v1" if g else "v1", "kind": okind, "name": oname}]
    out = {"kind": kind, "metadata": md}
    if kind == "Service":
        out["spec"] = {"type": "LoadBalancer" if o.get("lb") else "ClusterIP"}
    return out
name = os.path.basename(sys.argv[0])
a = sys.argv[1:]
reconcile()
rc = 0
if name == "aws":
    if a[:2] == ["eks", "list-clusters"]:
        print(os.environ["FAKE_SPOKE"])
    elif a[:2] == ["eks", "update-kubeconfig"]:
        open(a[a.index("--kubeconfig") + 1], "w").write("spoke\n")
    elif a[:2] == ["eks", "describe-cluster"]:
        print("vpc-spoke")
    elif a[:2] == ["elbv2", "describe-load-balancers"]:
        print(lbs())
else:
    kc = a[a.index("--kubeconfig") + 1] if "--kubeconfig" in a else ""
    a = [x for i, x in enumerate(a) if x != "--kubeconfig" and (i == 0 or a[i - 1] != "--kubeconfig")]
    hub = kc == os.environ["FAKE_HUB_KC"]
    verb = a[0]
    pos = [x for i, x in enumerate(a) if not x.startswith("-") and not (i and a[i - 1] in ("-n", "-o", "-p", "--type"))]
    ns = a[a.index("-n") + 1] if "-n" in a else None
    if hub:
        if verb == "get" and pos[1].startswith("appprojects"):
            print("appproject.argoproj.io/default")
        elif verb == "get":
            print(json.dumps({"spec": {}}))
        # patches of the sync window: accepted, no effect on in-cluster controllers
    elif verb == "get" and pos[1] in ("ingress,svc", "svc"):
        kinds = ("Ingress", "Service") if pos[1] == "ingress,svc" else ("Service",)
        print(json.dumps({"items": [item(k, o) for k, o in st["objs"].items() if o["kind"] in kinds]}))
    elif verb in ("get", "delete") and len(pos) >= 3:
        kind = pos[1].split(".")[0]
        kind = {"ingress": "Ingress", "svc": "Service"}.get(kind, kind)
        k = key(kind, pos[2], ns)
        if verb == "get":
            if k in st["objs"]:
                print(json.dumps(item(k, st["objs"][k])))
            else:
                rc = 1
        else:
            st["log"].append(["delete", k])
            st["objs"].pop(k, None)
    elif verb == "delete" and pos[1] in ("ingress", "pvc") and "--all" in a:
        for k in [k for k, o in st["objs"].items() if o["kind"] == {"ingress": "Ingress", "pvc": "PVC"}[pos[1]]]:
            del st["objs"][k]
            st["log"].append(["delete", k])
    reconcile()
save(); sys.exit(rc)
'''

FAKE_SLEEP = '#!/bin/sh\necho "$1" >> "$FAKE_CLOCK"\n'


def _state():
    objs = {
        "AppmodService/rust/rust-app": {"kind": "AppmodService"},
        "Ingress/rust/rust-app": {"kind": "Ingress", "owner": "AppmodService/rust/rust-app"},
        "AgentStack/agentgateway/gw-stack": {"kind": "AgentStack"},
        "Gateway/agentgateway/proxy": {"kind": "Gateway", "owner": "AgentStack/agentgateway/gw-stack"},
        "Service/agentgateway/proxy": {"kind": "Service", "lb": True, "owner": "Gateway/agentgateway/proxy"},
        "Service/default/plain-lb": {"kind": "Service", "lb": True},
        "Service/default/web": {"kind": "Service", "owner": "Deployment/default/web"},
        "Deployment/default/web": {"kind": "Deployment"},
    }
    templates = {k: dict(v) for k, v in objs.items() if k.split("/")[0] in ("Ingress", "Service", "Gateway") and v.get("owner")}
    groups = {"AppmodService": "kro.run", "AgentStack": "kro.run", "Gateway": "gateway.networking.k8s.io",
              "Deployment": "apps", "Ingress": "networking.k8s.io", "Service": ""}
    return {"objs": objs, "templates": templates, "groups": groups, "recreated": [], "log": []}


def _phase1(src):
    for c in src["tasks"]["destroy"]["cmds"]:
        t = c.get("cmd", "") if isinstance(c, dict) else (c if isinstance(c, str) else "")
        if "Phase 1 — draining" in t:
            return t
    raise AssertionError("Phase 1 cmd not found")


def _run(tmp):
    if not TASK:
        pytest.skip("go-task not on PATH")
    src = yaml.safe_load(open(TASKFILE))
    bindir = tmp / "bin"
    bindir.mkdir()
    for n in ("kubectl", "aws"):
        (bindir / n).write_text(FAKE.replace("{python}", sys.executable))
        (bindir / n).chmod(0o755)
    (bindir / "sleep").write_text(FAKE_SLEEP)
    (bindir / "sleep").chmod(0o755)
    state, clock = tmp / "state.json", tmp / "clock"
    state.write_text(json.dumps(_state()))
    clock.write_text("")
    (tmp / "config.yaml").write_text("resourcePrefix: acme\naws:\n  region: eu-west-3\n")
    hub_kc = tmp / "hub-kubeconfig"
    hub_kc.write_text("hub\n")
    gvars = {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")}
    gvars.update({"CONFIG_FILE": str(tmp / "config.yaml"), "HUB_KUBECONFIG": str(hub_kc),
                  "AWS_REGION": "eu-west-3", "RESOURCE_PREFIX": "acme", "LB_DRAIN_WAIT": "60"})
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
    return _run(tmp_path_factory.mktemp("owners"))


def test_exit_code(run):
    assert run[0].returncode == 0, run[0].stdout + run[0].stderr


def test_no_load_balancer_left_and_none_re_created(run):
    res, st, _w = run
    left = [k for k, o in st["objs"].items() if o["kind"] == "Ingress" or (o["kind"] == "Service" and o.get("lb"))]
    assert left == [], f"left: {left}, re-created: {st['recreated']}\n{res.stdout}"


def test_topmost_owners_deleted_workloads_untouched(run):
    _res, st, _w = run
    deleted = [e[1] for e in st["log"] if e[0] == "delete"]
    assert "AppmodService/rust/rust-app" in deleted
    assert "AgentStack/agentgateway/gw-stack" in deleted, "the Gateway's own owner was not walked up to"
    assert "Deployment/default/web" not in deleted, "an apps/v1 owner was deleted"


def test_gate_does_not_poll(run):
    assert run[2] < 60, f"{run[2]}s of polling"
