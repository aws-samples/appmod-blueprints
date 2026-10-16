"""Hermetic tests for kind-kro-ack `hub:destroy-addons`: Crossplane is not removed (step 8)
while an addon it manages AWS resources for is still being deleted.

Argo CD deletes an Application's resources one sync wave at a time. observability-aws's
first wave to go is its AMP scrapers, which take minutes to delete in AWS, so its later
waves (the AMP and AMG workspaces, the AMG security group) have not started when step 7's
per-addon 120 s run out. If step 8 then removes crossplane-base and crossplane, those
resources are never deleted by the addon teardown. Nor are they if step 7 has already
removed eks-capabilities-rbac-hub, the hub kro capability's RBAC for the Crossplane types
its GrafanaWorkspaceWithVpc renders: kro can then no longer delete it.

The cmds from step 7 through step 8 are read verbatim from
cluster-providers/kind-kro-ack/Taskfile.yaml and run under go-task's own interpreter with
the Taskfile's `set:` options (bash with the same options if go-task is not on PATH).
`kubectl` and `sleep` are fakes on PATH: a small model of the hub's ApplicationSets and
Applications on a simulated clock (`sleep` advances it; nothing is slept), in which an
Application finishes deleting a set time after its ApplicationSet is deleted. Every
ApplicationSet delete is recorded with the Applications still being deleted at that
moment. No cluster, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_addons_crossplane_wait.py -q
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
for _tool in ("bash", "jq"):
    if not shutil.which(_tool):
        pytest.skip(f"{_tool} not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
TASK = shutil.which("task")
HUB = "acme-hub"
XP = ["amp.aws.upbound.io", "grafana.aws.upbound.io", "iam.aws.upbound.io", "kro.run"]

FAKE = r'''#!{python} -I
import json, os, re, sys
STATE, LOG = os.environ["FAKE_STATE"], os.environ["FAKE_LOG"]
st = json.load(open(STATE))
def save():
    json.dump(st, open(STATE, "w"))
def log(*ev):
    with open(LOG, "a") as f:
        f.write(json.dumps(ev) + "\n")
def progress():
    for n, a in list(st["apps"].items()):
        if a.get("deleting_since") is not None and a.get("takes") is not None \
                and st["clock"] - a["deleting_since"] >= a["takes"]:
            del st["apps"][n]
def xp_pending():
    return sorted(n for n, a in st["apps"].items() if a.get("deleting_since") is not None
                  and any(g.endswith(".upbound.io") for g in a.get("groups", [])))
progress()
if os.path.basename(sys.argv[0]) == "sleep":
    st["clock"] += float(sys.argv[1])
    log("sleep", float(sys.argv[1]), st["clock"])
    progress(); save(); sys.exit(0)
args = sys.argv[1:]
jp = next((a.split("=", 1)[1] for a in args if a.startswith("jsonpath=")), None)
if jp is None and "-o" in args and args[args.index("-o") + 1].startswith("jsonpath="):
    jp = args[args.index("-o") + 1].split("=", 1)[1]
verb, what = args[0], args[1]
rc = 0
if verb == "get" and what == "applicationsets":
    for n, s in st["appsets"].items():
        print(f"{n} {s.get('wave', '')}")
elif verb == "get" and what == "applicationset":
    rc = 0 if args[2] in st["appsets"] else 1
elif verb == "get" and what == "applications" and "json" in args:
    items = []
    for n, a in st["apps"].items():
        md = {"name": n, "ownerReferences": [{"name": a["owner"]}]}
        if a.get("deleting_since") is not None:
            md["deletionTimestamp"] = "2026-10-16T21:59:34Z"
        items.append({"metadata": md, "status": {"resources": [
            {"group": g, "kind": "X"} if g else {"kind": "X"} for g in a.get("groups", [])]}})
    print(json.dumps({"items": items}))
elif verb == "get" and what == "applications" and jp:
    owner = re.search(r'name=="([^"]+)"', jp).group(1)
    kids = [n for n, a in st["apps"].items() if a["owner"] == owner]
    if ".metadata.finalizers" in jp:
        sys.stdout.write("".join('["resources-finalizer.argocd.argoproj.io"]' for _ in kids))
    else:
        sys.stdout.write("".join(k + ("\n" if '"\\n"' in jp else "") for k in kids))
elif verb == "get" and what == "pods":
    if st["providers_running"]:
        sys.stdout.write("provider-aws-amp-0 provider-aws-grafana-0 ")
elif verb == "patch":
    pass
elif verb == "delete" and what == "applicationset":
    n = args[2]
    log("delete-appset", n, st["clock"], xp_pending())
    st["appsets"].pop(n, None)
    for k, a in list(st["apps"].items()):
        if a["owner"] == n and a.get("deleting_since") is None:
            a["deleting_since"] = st["clock"]
            if a.get("takes") == 0:
                del st["apps"][k]
else:
    log("unexpected", args)
save()
sys.exit(rc)
'''


def _slice():
    """The task's vars and its cmds from step 7 (per-addon pass) through step 8."""
    with open(TASKFILE) as f:
        tf = yaml.safe_load(f)
    task = tf["tasks"]["hub:destroy-addons"]
    cmds = task["cmds"]
    first = next(i for i, c in enumerate(cmds) if isinstance(c, dict) and 'SKIP="{{.INFRA_STACK}}' in c.get("cmd", ""))
    last = next(i for i, c in enumerate(cmds) if isinstance(c, dict)
                and "for ADDON in kro-manifests-hub kro-manifests kro " in c.get("cmd", ""))
    return tf.get("set", []), dict(task.get("vars", {})), cmds[first:last + 1]


def _run(tmp_path, apps, providers_running=True):
    opts, tvars, cmds = _slice()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = FAKE.replace("{python}", sys.executable)
    for b in ("kubectl", "sleep"):
        (bindir / b).write_text(fake)
        (bindir / b).chmod(0o755)
    appsets = {"observability-aws": {"wave": "4"}, "kargo": {"wave": "3"},
               "eks-capabilities-rbac-hub": {"wave": "-3"},
               "kro-manifests-hub": {}, "crossplane-base": {}, "crossplane": {}}
    state, log = tmp_path / "state.json", tmp_path / "log.jsonl"
    state.write_text(json.dumps({"clock": 0, "appsets": appsets, "apps": apps,
                                 "providers_running": providers_running}))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_STATE=str(state), FAKE_LOG=str(log))
    tvars["KC"] = f"KUBECONFIG={tmp_path}/hub-kubeconfig kubectl"
    if TASK:
        t = tmp_path / "Taskfile.yml"
        t.write_text(yaml.safe_dump({"version": "3", "set": opts, "tasks": {
            "run": {"vars": tvars, "cmds": cmds}}}, sort_keys=False))
        res = subprocess.run([TASK, "-s", "-t", str(t), "run"], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=120)
    else:
        # One shell per cmd, as go-task runs them; every cmd here is ignore_error.
        out, rc = [], 0
        for i, c in enumerate(cmds):
            c = c["cmd"] if isinstance(c, dict) else c
            for k, v in tvars.items():
                v = re.sub(r"\{\{\.(\w+) \| default \"([^\"]*)\"\}\}", r"\2", str(v))
                c = c.replace("{{.%s}}" % k, v)
            script = tmp_path / f"step{i}.sh"
            script.write_text("".join(f"set -o {o}\n" for o in opts) + c)
            r = subprocess.run(["bash", str(script)], cwd=tmp_path, env=env,
                               capture_output=True, text=True, timeout=120)
            out.append(r.stdout)
        res = subprocess.CompletedProcess(["bash"], rc, "".join(out), "")
    events = [json.loads(line) for line in log.read_text().splitlines()]
    return res, events


def _deletes(events):
    return {e[1]: (e[2], e[3]) for e in events if e[0] == "delete-appset"}


def _obs(takes):
    return {"owner": "observability-aws", "groups": XP + [""], "takes": takes}


def test_crossplane_outlives_its_pending_deletes(tmp_path):
    # As live: observability-aws needs ~13 min after its delete; kargo stays stuck on a
    # finalizer that is not Crossplane's.
    res, events = _run(tmp_path, {f"observability-aws-{HUB}": _obs(780),
                                  f"kargo-{HUB}": {"owner": "kargo", "groups": ["", "kargo.akuity.io"],
                                                   "takes": None}})
    assert res.returncode == 0, res.stdout + res.stderr
    d = _deletes(events)
    for infra in ("kro-manifests-hub", "crossplane-base", "crossplane", "eks-capabilities-rbac-hub"):
        clock, pending = d[infra]
        assert pending == [], f"{infra} deleted at {clock:.0f}s while Crossplane still had to delete: {pending}"


def test_kro_keeps_its_hub_rbac_until_crossplane_is_gone(tmp_path):
    # The hub kro capability's only RBAC for the Crossplane types its instances render
    # (observability-aws's GrafanaWorkspaceWithVpc) is eks-capabilities-rbac-hub.
    res, events = _run(tmp_path, {f"observability-aws-{HUB}": _obs(780)})
    assert res.returncode == 0, res.stdout + res.stderr
    order = [e[1] for e in events if e[0] == "delete-appset"]
    assert order[-1] == "eks-capabilities-rbac-hub", order


def test_the_wait_is_bounded(tmp_path):
    limit = int(re.search(r'default "(\d+)"', str(_slice()[1].get("XP_DELETE_WAIT", 'default "0"'))).group(1))
    res, events = _run(tmp_path, {f"observability-aws-{HUB}": _obs(None)})
    assert res.returncode == 0, res.stdout + res.stderr
    waited = sum(e[1] for e in events if e[0] == "sleep" and e[1] == 15)
    assert waited <= limit, waited
    assert "crossplane" in _deletes(events), "step 8 never ran"


def test_no_wait_without_crossplane_deletes(tmp_path):
    # observability-aws done within step 7's 120 s; a stuck non-Crossplane app is not waited for.
    res, events = _run(tmp_path, {f"observability-aws-{HUB}": _obs(60),
                                  f"kargo-{HUB}": {"owner": "kargo", "groups": [""], "takes": None}})
    assert res.returncode == 0, res.stdout + res.stderr
    assert not [e for e in events if e[0] == "sleep" and e[1] == 15], res.stdout


def test_no_wait_when_no_provider_runs(tmp_path):
    res, events = _run(tmp_path, {f"observability-aws-{HUB}": _obs(None)}, providers_running=False)
    assert res.returncode == 0, res.stdout + res.stderr
    assert not [e for e in events if e[0] == "sleep" and e[1] == 15], res.stdout
    assert "crossplane" in _deletes(events)
