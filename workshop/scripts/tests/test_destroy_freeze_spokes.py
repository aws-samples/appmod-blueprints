"""Hermetic tests for option C of the drain fix: the provider's `hub:freeze-spokes`
(kind-kro-ack) turns automated sync off for everything targeting a spoke, and workshop
`destroy` calls it before Phase 1, so a drained load balancer is not re-created by Argo CD
self-heal. Then the drain waits (bounded) until no load balancer is left in the spoke VPC.

The cmds are read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and
workshop/Taskfile.yaml and run under go-task with `set: [errexit, nounset, pipefail]`.
kubectl, aws and sleep are fakes on PATH sharing one state file: Argo CD self-heal re-creates
a drained Service while the spoke Application still has automated sync, and an
ApplicationSet rewrites its Applications' syncPolicy from its template.

Run:  python -m pytest workshop/scripts/tests/test_destroy_freeze_spokes.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROVIDER_TF = os.environ.get("DESTROY_ADDONS_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
WORKSHOP_TF = os.environ.get("WORKSHOP_TASKFILE") or os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")
HUB, SPOKE = "acme-hub", "acme-spoke-dev"
AUTO = {"automated": {"prune": True, "selfHeal": True}}
FIN = ["resources-finalizer.argocd.argoproj.io"]

COMMON = r'''
import copy, fcntl, json, os, sys
STATE = os.environ["FAKE_STATE"]
_L = open(STATE + ".lock", "a"); fcntl.flock(_L, fcntl.LOCK_EX)
st = json.load(open(STATE))
def save():
    json.dump(st, open(STATE, "w"))
def reconcile():
    # ApplicationSet controller: Applications follow their template's syncPolicy.
    for n, a in st["apps"].items():
        o = a.get("owner")
        if o in st["appsets"]:
            a["syncPolicy"] = copy.deepcopy(st["appsets"][o]["syncPolicy"])
    # Argo CD self-heal on the spoke Application re-creates a drained Service.
    gw = st["apps"].get("agentgateway-" + os.environ["FAKE_SPOKE"])
    if not st["svc"] and gw and "automated" in gw.get("syncPolicy", {}):
        st["svc"] = True; st["recreated"] += 1
'''

FAKE_KUBECTL = "#!{python} -I\n" + COMMON + r'''
args = sys.argv[1:]
kc = args[args.index("--kubeconfig") + 1] if "--kubeconfig" in args else os.environ.get("KUBECONFIG", "")
args = [x for i, x in enumerate(args) if x != "--kubeconfig" and (i == 0 or args[i - 1] != "--kubeconfig")]
hub = kc == os.environ["FAKE_HUB_KC"]
pos = [x for i, x in enumerate(args) if not x.startswith("-") and not (i and args[i - 1] in ("-n", "-o", "-p", "--type"))]
verb, kind = pos[0], pos[1]
name = pos[2] if len(pos) > 2 else None
def opt(o):
    return args[args.index(o) + 1] if o in args else None
rc = 0
reconcile()
if hub:
    tbl = st["appsets"] if kind.startswith("applicationset") else st["apps"]
    if verb == "get":
        out = opt("-o") or ""
        if name:
            rc = 0 if name in tbl else 1
        elif out == "json":
            print(json.dumps({"items": [{"metadata": dict({"name": n}, **({"ownerReferences": [{"kind": "ApplicationSet", "name": a["owner"]}]} if a.get("owner") else {})),
                                         "spec": {"destination": a["dest"], "syncPolicy": a.get("syncPolicy", {})}}
                                        for n, a in st["apps"].items()]}))
        elif out.startswith("jsonpath="):
            print("\n".join(tbl))
    elif verb == "patch" and name in tbl:
        body = json.loads(opt("-p"))
        if opt("--type") == "json":
            for op in body:
                path = op["path"]
                if kind.startswith("applicationset") and path == "/spec/template/spec/syncPolicy/automated":
                    tbl[name]["syncPolicy"].pop("automated", None)
                elif path == "/spec/syncPolicy/automated":
                    tbl[name].setdefault("syncPolicy", {}).pop("automated", None)
            st["log"].append(["patch-json", kind[:14], name])
        else:
            pr = body.get("spec", {}).get("syncPolicy", {}).get("preserveResourcesOnDeletion")
            if pr is not None:
                tbl[name]["preserve"] = pr
            if body.get("metadata", {}).get("finalizers") == []:
                tbl[name]["finalizers"] = []
    elif verb == "delete" and name in tbl:
        o = tbl.pop(name)
        if kind.startswith("applicationset"):
            for n, a in list(st["apps"].items()):
                if a.get("owner") == name:
                    if o.get("preserve"):
                        a["owner"] = ""
                    else:
                        st["log"].append(["prune", n]); del st["apps"][n]
        elif o.get("finalizers"):
            st["log"].append(["prune", name])
    elif verb in ("patch", "delete"):
        rc = 1
else:
    if verb == "get" and kind == "svc":
        print(json.dumps({"items": [{"metadata": {"namespace": "agentgateway", "name": "proxy"}, "spec": {"type": "LoadBalancer"}}] if st["svc"] else []}))
    elif verb == "delete" and kind == "svc":
        st["svc"] = False
reconcile()
save(); sys.exit(rc)
'''

FAKE_AWS = "#!{python} -I\n" + COMMON + r'''
a = sys.argv[1:]
if a[:2] == ["eks", "list-clusters"]:
    print(os.environ["FAKE_SPOKE"])
elif a[:2] == ["eks", "update-kubeconfig"]:
    kc = a[a.index("--kubeconfig") + 1]
    if kc != os.environ["FAKE_HUB_KC"]:
        open(kc, "w").write("spoke\n")
elif a[:2] == ["eks", "describe-cluster"]:
    print("vpc-spoke")
elif a[:2] == ["elbv2", "describe-load-balancers"]:
    reconcile()
    print(1 if st["svc"] else 0)
save(); sys.exit(0)
'''

FAKE_SLEEP = '''#!/bin/sh
echo "$1" >> "$FAKE_CLOCK"
'''


def _state():
    def aset(sp):
        return {"syncPolicy": sp, "preserve": False}
    return {"svc": True, "recreated": 0, "log": [],
            "appsets": {"bootstrap": aset(dict(AUTO)), "cluster-addons": aset(dict(AUTO)),
                        "agentgateway": aset(dict(AUTO)), "cert-manager": aset(dict(AUTO)),
                        "clusters-kro": aset(dict(AUTO))},
            "apps": {
                "bootstrap": {"dest": {"name": "in-cluster"}, "syncPolicy": dict(AUTO), "finalizers": FIN},
                "cluster-addons": {"owner": "bootstrap", "dest": {"name": "in-cluster"}, "finalizers": FIN},
                f"agentgateway-{SPOKE}": {"owner": "agentgateway", "dest": {"name": SPOKE}, "finalizers": FIN},
                f"agentgateway-{HUB}": {"owner": "agentgateway", "dest": {"name": HUB}, "finalizers": FIN},
                f"cert-manager-{HUB}": {"owner": "cert-manager", "dest": {"name": HUB}, "finalizers": FIN},
                f"clusters-kro-{SPOKE}": {"owner": "clusters-kro", "dest": {"server": "https://kubernetes.default.svc"}},
            }}


def _cmd(c):
    return c.get("cmd", "") if isinstance(c, dict) else (c if isinstance(c, str) else "")


def _run(tmp, with_freeze=True):
    if not TASK:
        pytest.skip("go-task not on PATH")
    prov = yaml.safe_load(open(PROVIDER_TF))["tasks"]
    work = yaml.safe_load(open(WORKSHOP_TF))["tasks"]["destroy"]["cmds"]
    phase1 = next(_cmd(c) for c in work if "Phase 1 — draining" in _cmd(c))
    cmds = []
    if with_freeze:
        assert "hub:freeze-spokes" in prov, "provider has no hub:freeze-spokes"
        assert any("hub:freeze-spokes" in _cmd(c) for c in work), "destroy does not call hub:freeze-spokes"
        cmds += [_cmd(c) for c in prov["hub:freeze-spokes"]["cmds"] if "Freezing" in _cmd(c)]
    cmds.append(phase1)
    bindir = tmp / "bin"
    bindir.mkdir()
    for n, body in (("kubectl", FAKE_KUBECTL), ("aws", FAKE_AWS), ("sleep", FAKE_SLEEP)):
        (bindir / n).write_text(body.replace("{python}", sys.executable))
        (bindir / n).chmod(0o755)
    state, clock = tmp / "state.json", tmp / "clock"
    state.write_text(json.dumps(_state()))
    clock.write_text("")
    (tmp / "private").mkdir()
    hub_kc = tmp / "private" / "hub-kubeconfig"
    hub_kc.write_text("hub\n")
    (tmp / "config.yaml").write_text("resourcePrefix: acme\naws:\n  region: eu-west-3\n")
    gvars = {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")}
    gvars.update({"CONFIG_FILE": str(tmp / "config.yaml"), "HUB_KUBECONFIG": str(hub_kc),
                  "AWS_REGION": "eu-west-3", "HUB_CLUSTER_NAME": HUB, "ROOT_DIR": str(tmp),
                  "KC": f"KUBECONFIG={hub_kc} kubectl"})
    tf = {"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": gvars,
          "tasks": {"run": {"cmds": [{"cmd": c, "ignore_error": False} for c in cmds]}}}
    (tmp / "Taskfile.yml").write_text(yaml.safe_dump(tf, sort_keys=False))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(state),
               FAKE_CLOCK=str(clock), FAKE_SPOKE=SPOKE, FAKE_HUB_KC=str(hub_kc))
    res = subprocess.run([TASK, "-s", "run"], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    waited = sum(int(x) for x in clock.read_text().split() if x.isdigit())
    return res, json.loads(state.read_text()), waited


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("freeze"))


def test_exit_code(run):
    assert run[0].returncode == 0, run[0].stdout + run[0].stderr


def test_spoke_syncs_frozen_hub_rest_untouched(run):
    _res, st, _w = run
    assert "automated" not in st["appsets"]["agentgateway"]["syncPolicy"]
    assert "automated" not in st["apps"][f"agentgateway-{SPOKE}"]["syncPolicy"]
    assert "automated" in st["appsets"]["cert-manager"]["syncPolicy"], "hub-only ApplicationSet frozen"
    assert "automated" in st["appsets"]["clusters-kro"]["syncPolicy"], "in-cluster ApplicationSet frozen"


def test_generators_stopped_without_pruning(run):
    _res, st, _w = run
    assert "bootstrap" not in st["appsets"] and "cluster-addons" not in st["appsets"]
    assert [e for e in st["log"] if e[0] == "prune"] == [], st["log"]


def test_drain_sticks_and_no_lb_left(run):
    _res, st, waited = run
    assert st["svc"] is False and st["recreated"] == 0, st
    assert waited < 60, waited


def test_without_freeze_the_drain_is_undone(tmp_path):
    _res, st, _w = _run(tmp_path, with_freeze=False)
    assert st["recreated"] >= 1 and st["svc"] is True
