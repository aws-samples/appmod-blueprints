"""Hermetic tests for kind-kro-ack `hub:destroy-addons`, steps 7-10: the order in which
the hub's addons are removed, and that multi-acct is removed last without a prune.

multi-acct owns the per-cluster Namespaces and the CARM IAMRoleSelectors. After the hub
self-adoption pivot (#1033), Namespace <hub> holds the hub's own EksCluster, which `destroy`
flips to deletionPolicy=delete just before this task. If Argo CD prunes multi-acct, ACK
deletes the hub's Argo CD and ACK capability roles, and every addon removed after it waits
out its timeout on a resources-finalizer that can no longer complete.

The cmds of steps 7-10 are read verbatim from cluster-providers/kind-kro-ack/Taskfile.yaml
and run under go-task's own interpreter with the Taskfile's `set:` options (bash with
`set -euo pipefail` if go-task is not on PATH). `kubectl` and `sleep` are fakes on PATH:
a small stateful model of the ApplicationSets and Applications that records every write.
No cluster, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_addons_order.py -q
Set DESTROY_ADDONS_TASKFILE=<path> to run the same checks against another Taskfile.
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
TASKFILE = os.environ.get("DESTROY_ADDONS_TASKFILE") or os.path.join(
    REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
HUB = "acme-hub"

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
        if st.get("broken"):
            if not a.get("deleting"):
                log("stall", n)  # Argo CD can no longer reach the hub: the finalizer stays
            a["deleting"] = True
            return
        log("prune", n, a.get("owner", ""))
        if a.get("owner") == "multi-acct" and st.get("pivoted"):
            # Namespace <hub> pruned -> EksCluster GC'd -> ACK deletes the capability roles
            st["broken"] = True
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
        if st["apps"][name].get("deleting"):
            log("delete-app", name, "finalizer stripped")
            del st["apps"][name]
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

# The hub after steps 1-6, as on a live post-pivot hub: the addon ApplicationSets carry
# no sync-wave (only bootstrap-level ones do); their Applications carry the registry wave.
ADDON_WAVES = {
    "platform-manifests-post": "8", "devlake": "7", "keycloak": "6", "platform-manifests": "6",
    "backstage": "4", "observability-aws": "4", "cert-manager": "2", "metrics-server": "0",
    "external-secrets": "-1", "platform-manifests-bootstrap": "-1", "kro-clusters-rgds-hub": "-2",
    "eks-capabilities-rbac-hub": "-3", "ack-pod-identities": "-4", "multi-acct": "-5",
}
INFRA_WAVES = {"kro-manifests-hub": "-2", "kro-manifests": "-2", "kro": "-3",
               "crossplane-base": "3", "crossplane": "2"}
NO_CHILDREN = ["image-prepuller", "ack-iam"]  # disabled addons: an AppSet, no Applications


def _state():
    appsets, apps = {}, {}
    for name, wave in {**ADDON_WAVES, **INFRA_WAVES}.items():
        appsets[name] = {"wave": "", "preserve": True}
        apps[f"{name}-{HUB}"] = {"owner": name, "wave": wave,
                                 "finalizers": ["resources-finalizer.argocd.argoproj.io"]}
    for name in NO_CHILDREN:
        appsets[name] = {"wave": "", "preserve": True}
    appsets["fleet-secrets"] = {"wave": "1", "preserve": True}
    apps[f"fleet-secret-{HUB}"] = {"owner": "fleet-secrets", "wave": "",
                                  "finalizers": ["resources-finalizer.argocd.argoproj.io"]}
    return {"appsets": appsets, "apps": apps, "pivoted": True, "broken": False}


def _steps_7_to_10():
    with open(TASKFILE) as f:
        task = yaml.safe_load(f)["tasks"]["hub:destroy-addons"]
    cmds = task["cmds"]
    text = lambda c: c.get("cmd", "") if isinstance(c, dict) else c
    start = next(i for i, c in enumerate(cmds) if 'SKIP="{{.INFRA_STACK}}' in text(c))
    return task["vars"], [c for c in cmds[start:] if not (isinstance(c, dict) and "task" in c)]


def _render(s, tvars, root):
    s = s.replace("{{.KC}}", tvars["KC"]).replace("{{.INFRA_STACK}}", tvars["INFRA_STACK"])
    return re.sub(r"\{\{\.C_[A-Z]+\}\}", "", s.replace("{{.ROOT_DIR}}", str(root)))


def _run(tmp_path):
    tvars, cmds = _steps_7_to_10()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "kubectl").write_text(FAKE_KUBECTL.replace("{python}", sys.executable))
    (bindir / "sleep").write_text(FAKE_SLEEP)
    for f in ("kubectl", "sleep"):
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
    return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.fixture(scope="module")
def events(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("destroy-addons"))


def _wave(appset):
    return int({**ADDON_WAVES, **INFRA_WAVES}.get(appset, "0"))


def test_multi_acct_is_never_pruned(events):
    pruned = [e[1] for e in events if e[0] == "prune" and e[2] == "multi-acct"]
    assert pruned == [], "Argo CD pruned multi-acct (Namespace <hub> + CARM selectors): " + str(pruned)


def test_multi_acct_goes_after_every_other_addon(events):
    gone = [i for i, e in enumerate(events) if e[0] == "delete-appset"]
    ma = [i for i in gone if events[i][1] == "multi-acct"]
    assert ma, "multi-acct ApplicationSet never removed"
    later = [events[i][1] for i in gone if i > ma[0]]
    assert later == [], "removed after multi-acct: " + ", ".join(later)


def test_addons_go_in_descending_application_wave(events):
    infra = set(INFRA_WAVES) | set(_steps_7_to_10()[0]["INFRA_STACK"].split()) \
        | {"fleet-secrets", "multi-acct"} | set(NO_CHILDREN)
    order = [e[1] for e in events if e[0] == "delete-appset" and e[1] not in infra]
    assert order == sorted(order, key=_wave, reverse=True), \
        "step 7 order vs Application waves: " + ", ".join(f"{a}({_wave(a)})" for a in order)


def test_no_addon_waits_out_its_timeout(events):
    stalled = [e[1] for e in events if e[0] == "stall"]
    waited = sum(e[1] for e in events if e[0] == "sleep")
    assert stalled == [], f"{len(stalled)} Applications stuck on their finalizer, {waited}s of waits"
    assert waited < 300, f"{waited}s of fixed waits"
