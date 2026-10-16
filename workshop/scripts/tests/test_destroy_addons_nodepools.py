"""Hermetic tests for kind-kro-ack `hub:destroy-addons`: the Karpenter NodePools that the
platform controllers run on are not pruned while those controllers still have work to do.

`platform-manifests-bootstrap` owns the hub's NodePools (a consumer overlay's pools, such
as the workshop's system-peeks and general-purpose-peeks, plus gpu/trainium). The
workshop overlay pins cert-manager, external-secrets, crossplane, the load balancer
controller, argo-* and others to `karpenter.sh/nodepool: system-peeks`. If the teardown
prunes platform-manifests-bootstrap as an ordinary addon, Auto Mode drains those nodes and
every pinned controller removed after it is already Pending.

The task's cmds are read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml and
run under go-task's own interpreter with the Taskfile's `set:` options (bash with
`set -euo pipefail` if go-task is not on PATH). `kubectl`, `aws` and `sleep` are fakes on
PATH: a small stateful model of the hub's ApplicationSets and Applications that records
every write. The addon waves and the pinned addons are read from the repo (registry and
workshop overlay), so the model follows them. No cluster, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_addons_nodepools.py -q
Set DESTROY_ADDONS_TASKFILE=<path> to run the same checks against another Taskfile.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.environ.get("DESTROY_ADDONS_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
HUB = "acme-hub"
SPOKES = ["acme-spoke-dev", "acme-spoke-prod"]
POOLS = "platform-manifests-bootstrap"
PIN = "karpenter.sh/nodepool: system-peeks"

# Addons with Applications on a workshop hub (as on a live kind-kro-ack hub). Their waves
# come from the registry. Bootstrap-level AppSets (bootstrap, cluster-addons, ...) are left
# out: steps 1-4.6 handle them by name.
HUB_ADDONS = [
    "ack-pod-identities", "argo-events", "argo-rollouts", "argo-workflows",
    "argocd-gitlab-repo-creds", "aws-load-balancer-controller", "backstage", "cert-manager",
    "crossplane", "crossplane-base", "default-storage-class", "devlake",
    "eks-capabilities-rbac-hub", "env-config", "external-dns", "external-secrets",
    "grafana-dashboards", "grafana-operator", "image-prepuller", "ingress-class-alb",
    "jupyterhub", "kargo", "keycloak", "kro-amp-incident-rgd-hub", "kro-clusters-rgds-hub",
    "kro-manifests-hub", "kro-ray-rgd-hub", "kube-state-metrics", "kubevela",
    "metrics-server", "multi-acct", "observability-aws", "platform-manifests", POOLS,
    "platform-manifests-post", "podidentity-pod-restart", "prometheus-node-exporter",
    "ray-operator", "spark-operator",
]
NO_CHILDREN = ["ack-iam", "ack-eks", "kro"]  # AppSets that generate nothing for the hub

FAKE_KUBECTL = r'''#!{python} -I
"""Fake kubectl: ApplicationSets/Applications in argocd, Argo CD prune semantics."""
import json, os, re, sys
STATE, LOG = os.environ["FAKE_K8S_STATE"], os.environ["FAKE_K8S_LOG"]
st = json.load(open(STATE))
args = sys.argv[1:]
def log(*ev):
    with open(LOG, "a") as f:
        f.write(json.dumps(ev) + "\n")
def opt(name):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None
pos = [a for i, a in enumerate(args) if not a.startswith("-")
       and not (i and args[i - 1] in ("-n", "-o", "-p", "--type"))]
verb, kind = pos[0], pos[1]
name = pos[2] if len(pos) > 2 else None
if "/" in kind:
    kind, name = kind.split("/", 1)
kind = "appset" if kind.startswith("applicationset") else "app"
FIN = "resources-finalizer.argocd.argoproj.io"

def item(k, n):
    o = (st["appsets"] if k == "appset" else st["apps"])[n]
    md = {"name": n}
    if o.get("wave"):
        md["annotations"] = {"argocd.argoproj.io/sync-wave": o["wave"]}
    if k == "app":
        if o.get("owner"):
            md["ownerReferences"] = [{"kind": "ApplicationSet", "name": o["owner"]}]
        if o.get("finalizers"):
            md["finalizers"] = o["finalizers"]
    return {"metadata": md}

def path_get(obj, path):
    for part in re.split(r"(?<!\\)\.", path.strip(".")):
        part = part.replace("\\.", ".")
        m = re.fullmatch(r"(.+)\[(\d+)\]", part)
        key, idx = (m.group(1), int(m.group(2))) if m else (part, None)
        obj = obj.get(key) if isinstance(obj, dict) else None
        if idx is not None:
            obj = obj[idx] if isinstance(obj, list) and len(obj) > idx else None
        if obj is None:
            return ""
    return json.dumps(obj) if isinstance(obj, list) else str(obj)

def jsonpath(items, expr):
    m = re.fullmatch(r"\{range \.items\[(.*?)\]\}(.*)\{end\}", expr)
    sel, body = m.group(1), m.group(2)
    f = re.fullmatch(r'\?\(@(\S+?)=="([^"]*)"\)', sel)
    out = []
    for it in items:
        if f and path_get(it, f.group(1)) != f.group(2):
            continue
        for tok in re.findall(r"\{([^{}]*)\}", body):
            out.append(json.loads(tok) if tok.startswith('"') else path_get(it, tok))
    sys.stdout.write("".join(out))

def remove_app(n, why):
    a = st["apps"][n]
    if FIN in a.get("finalizers", []):
        log("prune", n, a.get("owner", ""))
    else:
        log("delete-app", n, why)
    del st["apps"][n]

def children(owner):
    return [n for n, a in st["apps"].items() if a.get("owner") == owner]

rc = 0
if verb == "get":
    out = opt("-o") or ""
    objs = st["appsets"] if kind == "appset" else st["apps"]
    if name:
        rc = 0 if name in objs else 1
    elif out == "name":
        prefix = "applicationset.argoproj.io/" if kind == "appset" else "application.argoproj.io/"
        print("\n".join(prefix + n for n in objs))
    elif out.startswith("jsonpath="):
        jsonpath([item(kind, n) for n in objs], out[len("jsonpath="):])
elif verb == "patch":
    p = json.loads(opt("-p"))
    if kind == "appset" and name in st["appsets"]:
        pr = p.get("spec", {}).get("syncPolicy", {}).get("preserveResourcesOnDeletion")
        if pr is not None:
            st["appsets"][name]["preserve"] = pr
            log("patch-appset", name, "preserve" if pr else "prune")
    elif kind == "app" and name in st["apps"] and p.get("metadata", {}).get("finalizers") == []:
        st["apps"][name]["finalizers"] = []
        log("strip", name)
    elif kind == "app" and name in st["apps"]:
        pass
    else:
        rc = 1
elif verb == "delete":
    if kind == "appset":
        if name not in st["appsets"]:
            rc = 1
        else:
            a = st["appsets"].pop(name)
            mode = "orphan" if opt("--cascade") == "orphan" else ("preserve" if a.get("preserve") else "prune")
            log("delete-appset", name, mode)
            for c in children(name):
                if mode == "orphan":
                    st["apps"][c]["owner"] = ""
                else:
                    if mode == "preserve":
                        st["apps"][c]["finalizers"] = []
                    remove_app(c, "appset " + name)
    elif "--all" in args:
        for n in list(st["apps"]):
            remove_app(n, "--all")
    elif name in st["apps"]:
        remove_app(name, "explicit")
    else:
        rc = 1
json.dump(st, open(STATE, "w"))
sys.exit(rc)
'''

FAKE_SLEEP = '''#!/bin/sh
printf '["sleep", %s]\\n' "$1" >> "$FAKE_K8S_LOG"
'''
FAKE_AWS = '''#!/bin/sh
exit 0
'''


def _registry():
    """AppSet name -> (wave, values dir), the way the appset chart derives them."""
    reg = {}
    for f in sorted(glob.glob(os.path.join(REPO, "gitops", "addons", "registry", "*.yaml"))):
        if os.path.basename(f).startswith("_"):
            continue
        with open(f) as fh:
            for key, cfg in (yaml.safe_load(fh) or {}).items():
                if not isinstance(cfg, dict):
                    continue
                name = key.replace("_", "-")
                wave = (cfg.get("annotationsAppSet") or {}).get("argocd.argoproj.io/sync-wave", "0")
                reg[name] = (str(wave), cfg.get("chartName") or name)
    return reg


REGISTRY = _registry()


def _pinned():
    """AppSets whose workshop-overlay values pin them to the system-peeks NodePool."""
    out = set()
    for name, (_, vdir) in REGISTRY.items():
        p = os.path.join(REPO, "workshop", "overlay", "configs", vdir, "values.yaml")
        if name != POOLS and os.path.exists(p) and PIN in open(p).read():
            out.add(name)
    return out


PINNED = _pinned()


def _state():
    appsets, apps = {}, {}
    fin = ["resources-finalizer.argocd.argoproj.io"]
    for name in HUB_ADDONS:
        appsets[name] = {"wave": "", "preserve": True}
        apps[f"{name}-{HUB}"] = {"owner": name, "wave": REGISTRY[name][0], "finalizers": list(fin)}
    for spoke in SPOKES:  # the spokes' pools: their clusters are already gone at this point
        apps[f"{POOLS}-{spoke}"] = {"owner": POOLS, "wave": REGISTRY[POOLS][0], "finalizers": list(fin)}
    for name in NO_CHILDREN:
        appsets[name] = {"wave": "", "preserve": True}
    appsets["fleet-secrets"] = {"wave": "1", "preserve": True}
    apps[f"fleet-secret-{HUB}"] = {"owner": "fleet-secrets", "wave": "", "finalizers": list(fin)}
    return {"appsets": appsets, "apps": apps}


def _cmds():
    with open(TASKFILE) as f:
        task = yaml.safe_load(f)["tasks"]["hub:destroy-addons"]
    text = lambda c: c.get("cmd", "") if isinstance(c, dict) else c
    cmds = [c for c in task["cmds"] if not (isinstance(c, dict) and "task" in c)]
    return task["vars"], [c for c in cmds if "update-kubeconfig" not in text(c)]


def _render(s, tvars, root):
    s = s.replace("{{.KC}}", tvars["KC"]).replace("{{.INFRA_STACK}}", tvars["INFRA_STACK"])
    return re.sub(r"\{\{\.C_[A-Z]+\}\}", "", s.replace("{{.ROOT_DIR}}", str(root)))


def _run(tmp_path):
    tvars, cmds = _cmds()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "kubectl").write_text(FAKE_KUBECTL.replace("{python}", sys.executable))
    (bindir / "sleep").write_text(FAKE_SLEEP)
    (bindir / "aws").write_text(FAKE_AWS)
    for f in ("kubectl", "sleep", "aws"):
        (bindir / f).chmod(0o755)
    state, log = tmp_path / "state.json", tmp_path / "log.jsonl"
    state.write_text(json.dumps(_state()))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_K8S_STATE=str(state), FAKE_K8S_LOG=str(log))
    if TASK:
        tf = tmp_path / "Taskfile.yml"
        tf.write_text(yaml.safe_dump({
            "version": "3", "set": ["errexit", "nounset", "pipefail"],
            "vars": {k: "" for k in ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP")},
            "tasks": {"run": {"vars": tvars, "cmds": cmds}}}, sort_keys=False))
        res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=300)
        assert res.returncode == 0, res.stdout + res.stderr
    else:
        for i, c in enumerate(cmds):
            script = tmp_path / f"cmd{i}.sh"
            script.write_text("set -euo pipefail\n" + _render(
                c["cmd"] if isinstance(c, dict) else c, tvars, tmp_path))
            res = subprocess.run(["bash", str(script)], cwd=tmp_path, env=env,
                                 capture_output=True, text=True, timeout=300)
            assert res.returncode == 0 or (isinstance(c, dict) and c.get("ignore_error")), res.stderr
    return [json.loads(line) for line in log.read_text().splitlines()], json.loads(state.read_text())


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("destroy-addons-nodepools"))


def test_model_has_pinned_controllers():
    # Guards the harness itself: the overlay still pins controllers to system-peeks.
    assert {"cert-manager", "external-secrets", "crossplane"} <= PINNED, sorted(PINNED)


def test_nodepools_are_not_pruned(run):
    events, _ = run
    pruned = [e[1] for e in events if e[0] == "prune" and e[1].startswith(POOLS + "-")]
    assert pruned == [], "Argo CD pruned the NodePools' Applications: " + ", ".join(pruned)


def test_pinned_controllers_keep_their_nodes(run):
    events, _ = run
    gone = [i for i, e in enumerate(events) if e[0] == "prune" and e[1] == f"{POOLS}-{HUB}"]
    if not gone:
        return
    late = [e[1][: -len(HUB) - 1] for e in events[gone[0]:]
            if e[0] in ("prune", "delete-app") and e[1].endswith("-" + HUB)
            and e[1][: -len(HUB) - 1] in PINNED]
    assert late == [], ("removed after their NodePools were pruned (already evicted, Pending): "
                        + ", ".join(late))


def test_nodepool_addon_leaves_no_argo_objects(run):
    _, state = run
    left = [n for n in state["apps"] if n.startswith(POOLS + "-")]
    assert POOLS not in state["appsets"] and left == [], (state["appsets"].keys(), left)


def test_every_other_hub_addon_is_still_pruned(run):
    events, _ = run
    pruned = {e[1] for e in events if e[0] == "prune"}
    # multi-acct is left out: #1078 removes it last without a prune.
    missing = [a for a in HUB_ADDONS
               if a not in (POOLS, "multi-acct") and f"{a}-{HUB}" not in pruned]
    assert missing == [], "no longer removed with a prune: " + ", ".join(missing)
