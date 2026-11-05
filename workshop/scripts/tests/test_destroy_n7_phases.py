"""Hermetic tests for the workshop `destroy` fixes from the N-7 teardown timeout:

1. Phase 2.5 (DevLake RDS) targets the kro RelationalDatabase / ACK resources the devlake
   addon renders today, keeps the legacy Crossplane path only when its CRDs are served,
   never aborts on a CRD the hub does not serve (the original N-7 errexit/pipefail abort),
   stops the Argo CD chain that would re-create the instance (top-down) before deleting
   it, waits bounded, and does not wait at all when it deleted nothing.
2. Phase 2 (`spokes:disable-all`) no longer exits 0 having deleted nothing when the
   fleet-config overlay is unreachable: it prints the (redacted) clone error and falls
   back to the spoke objects on the hub, never the hub's own, another prefix's, or a
   retained one.
3. Every destroy phase writes a best-effort "<phase> <utc>" SSM phase marker.
4. No statement-level `[ ... ] && cmd` (an errexit trap) in the changed blocks.

The cmds are read verbatim from workshop/Taskfile.yaml and run under go-task's own
interpreter with the Taskfile's `set:` options (bash with the same options if go-task is
not on PATH). `kubectl`, `aws`, `git` and `sleep` are fakes on PATH over a JSON state on a
simulated clock (`sleep` advances it; nothing is slept). No cluster, no AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_n7_phases.py -q
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
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
TASK = shutil.which("task")
PREFIX, HUB, REGION = "acme", "acme-hub", "us-west-2"
SECRET = "s3cr3t-p@ss"

RDB_KIND = "relationaldatabases.kro.run"
APP, APPSET = "applications.argoproj.io", "applicationsets.argoproj.io"
ACK_KINDS = ["dbinstances.rds.services.k8s.aws", "dbclusters.rds.services.k8s.aws",
             "dbsubnetgroups.rds.services.k8s.aws", "securitygroups.ec2.services.k8s.aws"]
XP_MR_KINDS = ["securitygroups.ec2.aws.upbound.io", "clusters.rds.aws.upbound.io",
               "subnetgroups.rds.aws.upbound.io"]

FAKE = r'''#!{python} -I
import json, os, sys
STATE, LOG = os.environ["FAKE_STATE"], os.environ["FAKE_LOG"]
st = json.load(open(STATE))
me = os.path.basename(sys.argv[0])
def save():
    json.dump(st, open(STATE, "w"))
def log(*ev):
    with open(LOG, "a") as f:
        f.write(json.dumps(ev) + "\n")
def progress():
    for kind, objs in st["objs"].items():
        for k, o in list(objs.items()):
            if o.get("gone_at") is not None and st["clock"] >= o["gone_at"]:
                del objs[k]
progress()
rc = 0
if me == "sleep":
    st["clock"] += float(sys.argv[1]); log("sleep", float(sys.argv[1])); progress()
elif me == "git":
    log("git", sys.argv[1:])
    if st.get("git_fails"):
        url = next(a for a in sys.argv[1:] if a.startswith("https://"))
        sys.stderr.write("Cloning into '/tmp/x'...\nfatal: unable to access '%s/': Could not resolve host\n" % url)
        rc = 128
elif me == "aws":
    a = sys.argv[1:]
    log("aws", a)
    if a[:2] == ["ssm", "put-parameter"]:
        rc = st.get("aws_rc", 0)
    elif a[:2] == ["eks", "describe-cluster"]:
        rc = 0 if a[a.index("--name") + 1] in st.get("eks_live", []) else 254
    elif a[:2] == ["eks", "update-kubeconfig"]:
        rc = 0
    else:
        rc = 0
else:  # kubectl
    a, pos, flags = sys.argv[1:], [], {}
    i = 0
    while i < len(a):
        x = a[i]
        if x in ("-n", "-o", "--kubeconfig", "--type", "-p"):
            flags[x] = a[i + 1]; i += 2; continue
        if x.startswith("-o=") or x.startswith("-o"):
            if x.startswith("-o") and len(x) > 2:
                flags["-o"] = x[2:].lstrip("="); i += 1; continue
        if x.startswith("-"):
            flags[x] = True; i += 1; continue
        pos.append(x); i += 1
    verb = pos[0]; kind = pos[1] if len(pos) > 1 else ""
    name = pos[2] if len(pos) > 2 else None
    ns = flags.get("-n")
    objs = st["objs"].get(kind)
    if kind == "crd" and verb == "get":
        rc = 0 if name in st["crds"] else 1
    elif verb in ("get", "delete", "patch") and kind != "crd" and kind not in st["crds"] \
            and kind not in ("applications.argoproj.io", "applicationsets.argoproj.io"):
        sys.stderr.write('error: the server doesn\'t have a resource type "%s"\n' % kind); rc = 1
    elif verb == "get":
        objs = objs or {}
        if name:
            o = objs.get("%s/%s" % (ns or "", name))
            if o is None:
                rc = 1
            elif flags.get("-o") == "json":
                print(json.dumps(o))
        else:
            items = [o for k, o in objs.items() if flags.get("-A") or k.split("/")[0] == (ns or "")]
            if flags.get("-o") == "json":
                print(json.dumps({"items": items}))
            elif flags.get("-o") == "name":
                for o in items:
                    print("%s/%s" % (kind, o["metadata"]["name"]))
            else:
                for o in items:
                    print("%s %s" % (o["metadata"].get("namespace", ""), o["metadata"]["name"]))
    elif verb == "delete":
        log("delete", kind, ns, name or ("--all" if flags.get("--all") else None))
        objs = objs or {}
        keys = list(objs) if flags.get("--all") else ["%s/%s" % (ns or "", name)]
        for k in keys:
            if k not in objs:
                continue
            if kind == "relationaldatabases.kro.run":
                del objs[k]
                for ck, cobjs in st["objs"].items():
                    for o in cobjs.values():
                        if any(r.get("kind") == "RelationalDatabase" for r in o["metadata"].get("ownerReferences", [])):
                            if st.get("children_takes") is not None and o.get("gone_at") is None:
                                o["gone_at"] = st["clock"] + st["children_takes"]
            elif kind in ("eksclusterwithvpcs.kro.run", "platformclusters.platform.gitops.io"):
                del objs[k]
            else:
                del objs[k]
    elif verb == "patch":
        log("patch", kind, ns, name, flags.get("-p"))
    else:
        log("unexpected", a)
save()
sys.exit(rc)
'''


def _taskfile():
    with open(TASKFILE) as f:
        return yaml.safe_load(f)


def _globals(tmp_path):
    return {"REPO": str(tmp_path), "RESOURCE_PREFIX": PREFIX, "AWS_REGION": REGION,
            "HUB_CLUSTER_NAME": HUB, "GIT_USERNAME": "user1", "PLATFORM_DIR": str(tmp_path),
            "C_STEP": "", "C_OK": "", "C_ERR": "", "C_INFO": "", "C_RESET": ""}


def _cmd_text(c):
    return c.get("cmd") if isinstance(c, dict) else c


def _destroy_cmds():
    return [c for c in _taskfile()["tasks"]["destroy"]["cmds"] if isinstance(_cmd_text(c), str)]


def _phase25_cmd():
    return next(c for c in _destroy_cmds() if "Phase 2.5 — releasing the DevLake RDS" in _cmd_text(c))


def _run(tmp_path, cmds, tvars, state):
    tf = _taskfile()
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = FAKE.replace("{python}", sys.executable)
    for b in ("kubectl", "sleep", "aws", "git"):
        (bindir / b).write_text(fake)
        (bindir / b).chmod(0o755)
    (tmp_path / "private").mkdir(exist_ok=True)
    st, log = tmp_path / "state.json", tmp_path / "log.jsonl"
    state.setdefault("clock", 0)
    state.setdefault("objs", {})
    st.write_text(json.dumps(state))
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(st), FAKE_LOG=str(log))
    gvars = _globals(tmp_path)
    if TASK:
        t = tmp_path / "Taskfile.yml"
        t.write_text(yaml.safe_dump({"version": "3", "set": tf.get("set", []), "vars": gvars,
                                     "tasks": {"run": {"vars": tvars, "cmds": cmds}}}, sort_keys=False))
        res = subprocess.run([TASK, "-s", "-t", str(t), "run"], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=120)
    else:
        allv = dict(gvars, **{k: re.sub(r"\{\{\.(\w+) \| default \"([^\"]*)\"\}\}", r"\2", str(v))
                              for k, v in tvars.items()})
        out, rc = [], 0
        for i, c in enumerate(cmds):
            c = _cmd_text(c)
            for _ in range(3):
                for k, v in allv.items():
                    c = c.replace("{{.%s}}" % k, str(v))
            script = tmp_path / f"step{i}.sh"
            script.write_text("".join(f"set -o {o}\n" for o in tf.get("set", [])) + c)
            r = subprocess.run(["bash", str(script)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
            out.append(r.stdout + r.stderr)
            if r.returncode:
                rc = r.returncode
                break
        res = subprocess.CompletedProcess(["bash"], rc, "".join(out), "")
    events = [json.loads(line) for line in log.read_text().splitlines()]
    return res, events, json.loads(st.read_text())


# ------------------------------------------------------------------ Phase 2.5

def _p25_vars(wait="900"):
    v = dict(_taskfile()["tasks"]["destroy"]["vars"])
    v.pop("PROVIDER", None)
    v["HUB_KUBECONFIG"] = "/dev/null"
    v["RDS_DELETE_WAIT"] = wait
    return v


def _obj(kind, ns, oname, ann=None, owners=None, **spec):
    md = {"name": oname, "namespace": ns}
    if ann:
        md["annotations"] = ann
    if owners:
        md["ownerReferences"] = owners
    return {"apiVersion": kind, "kind": kind, "metadata": md, "spec": spec}


def _kro_state(children_takes=60):
    """The devlake RelationalDatabase rendered by devlake-acme-hub, generated by the
    devlake appset, rendered by cluster-addons, generated by the cluster-addons appset,
    rendered by bootstrap, generated by the bootstrap appset (applied by the install)."""
    trk = lambda app, kind, ns, n: {"argocd.argoproj.io/tracking-id": f"{app}:argoproj.io/{kind}:{ns}/{n}"}
    own = lambda n: [{"kind": "ApplicationSet", "name": n}]
    objs = {
        RDB_KIND: {"devlake/devlake-mysql": _obj(RDB_KIND, "devlake", "devlake-mysql", ann={
            "argocd.argoproj.io/tracking-id": "devlake-acme-hub:kro.run/RelationalDatabase:devlake/devlake-mysql"})},
        APP: {
            "argocd/devlake-acme-hub": _obj(APP, "argocd", "devlake-acme-hub", owners=own("devlake")),
            "argocd/cluster-addons": _obj(APP, "argocd", "cluster-addons", owners=own("cluster-addons")),
            "argocd/bootstrap": _obj(APP, "argocd", "bootstrap", owners=own("bootstrap")),
        },
        APPSET: {
            "argocd/devlake": _obj(APPSET, "argocd", "devlake", ann=trk("cluster-addons", "ApplicationSet", "argocd", "devlake")),
            "argocd/cluster-addons": _obj(APPSET, "argocd", "cluster-addons", ann=trk("bootstrap", "ApplicationSet", "argocd", "cluster-addons")),
            "argocd/bootstrap": _obj(APPSET, "argocd", "bootstrap"),
        },
    }
    ref = [{"kind": "RelationalDatabase", "name": "devlake-mysql"}]
    for k in ACK_KINDS:
        objs[k] = {f"devlake/devlake-mysql-{k.split('.')[0]}": _obj(k, "devlake", f"devlake-mysql-{k.split('.')[0]}", owners=ref)}
    # An unrelated ACK SG in the namespace (not owned by the instance) is never waited for.
    objs["securitygroups.ec2.services.k8s.aws"]["devlake/other"] = _obj("sg", "devlake", "other")
    return {"crds": [RDB_KIND] + ACK_KINDS, "objs": objs, "children_takes": children_takes}


def test_p25_no_crds_does_not_abort_and_does_not_wait(tmp_path):
    # The int1104 case: a hub serving none of these CRDs. Must not abort (errexit/pipefail)
    # and must not wait.
    res, events, _ = _run(tmp_path, [_phase25_cmd()], _p25_vars(), {"crds": []})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "nothing to wait for" in res.stdout, res.stdout
    assert not [e for e in events if e[0] == "sleep"]
    assert not [e for e in events if e[0] == "delete"]


def test_p25_crossplane_leftovers_without_claims_are_not_waited_for(tmp_path):
    # The rc8 B case: Crossplane installed, Upbound MRs present but no DevLake claim to
    # delete. The old code waited its full 15 min here.
    xp = {k: {f"ns/{i}": _obj(k, "ns", str(i))} for i, k in enumerate(XP_MR_KINDS)}
    res, events, _ = _run(tmp_path, [_phase25_cmd()], _p25_vars(),
                          {"crds": XP_MR_KINDS + ["relationaldatabases.awsblueprints.io"], "objs": xp})
    assert res.returncode == 0, res.stdout + res.stderr
    assert not [e for e in events if e[0] == "sleep"], res.stdout


def test_p25_kro_stops_argo_chain_top_down_then_deletes_and_waits(tmp_path):
    res, events, st = _run(tmp_path, [_phase25_cmd()], _p25_vars(), _kro_state(children_takes=60))
    assert res.returncode == 0, res.stdout + res.stderr
    dels = [(e[1], e[3]) for e in events if e[0] == "delete"]
    assert dels == [(APPSET, "bootstrap"), (APP, "bootstrap"), (APPSET, "cluster-addons"),
                    (APP, "cluster-addons"), (APPSET, "devlake"), (APP, "devlake-acme-hub"),
                    (RDB_KIND, "devlake-mysql")], dels
    patches = {(e[1], e[3]): e[4] for e in events if e[0] == "patch"}
    for n in ("bootstrap", "cluster-addons", "devlake"):
        assert "preserveResourcesOnDeletion" in patches[(APPSET, n)]
    # Ancestors are orphaned (finalizer stripped); the app rendering the instance is not,
    # so its own resources-finalizer still cascades to the rest of the chart.
    assert '"finalizers":[]' in patches[(APP, "bootstrap")]
    assert '"finalizers":[]' in patches[(APP, "cluster-addons")]
    assert (APP, "devlake-acme-hub") not in patches
    slept = sum(e[1] for e in events if e[0] == "sleep")
    assert 60 <= slept <= 70, slept
    assert "DevLake RDS resources deleted" in res.stdout, res.stdout


def test_p25_kro_wait_is_bounded(tmp_path):
    res, events, _ = _run(tmp_path, [_phase25_cmd()], _p25_vars(wait="120"), _kro_state(children_takes=None))
    assert res.returncode == 0, res.stdout + res.stderr
    assert sum(e[1] for e in events if e[0] == "sleep") <= 120
    assert "still present after 120s" in res.stdout, res.stdout


def test_p25_kro_instance_without_argo_owner_is_deleted_directly(tmp_path):
    s = _kro_state(children_takes=0)
    s["objs"][RDB_KIND]["devlake/devlake-mysql"]["metadata"].pop("annotations")
    s["objs"][APP], s["objs"][APPSET] = {}, {}
    res, events, _ = _run(tmp_path, [_phase25_cmd()], _p25_vars(), s)
    assert res.returncode == 0, res.stdout + res.stderr
    assert [(e[1], e[3]) for e in events if e[0] == "delete"] == [(RDB_KIND, "devlake-mysql")]


# ------------------------------------------------------------------ Phase 2

def _disable_all():
    t = _taskfile()["tasks"]["spokes:disable-all"]
    tvars = {"GIT_DOMAIN": "git.example.test", "GIT_PASSWORD": SECRET}
    return t["cmds"], tvars


def _kro_cluster(name, ns=None, **spec):
    spec.setdefault("name", name)
    return _obj("eksclusterwithvpcs.kro.run", ns or name, name, **spec)


def test_p2_overlay_unreachable_falls_back_to_hub(tmp_path):
    kro = {
        f"{HUB}/{HUB}": _kro_cluster(HUB, fleetMember="control-plane", resourcePrefix=PREFIX, deletionPolicy="retain"),
        "acme-spoke-dev/acme-spoke-dev": _kro_cluster("acme-spoke-dev", resourcePrefix=PREFIX),
        "acme-spoke-prod/acme-spoke-prod": _kro_cluster("acme-spoke-prod", resourcePrefix=PREFIX),
        "acme-keep/acme-keep": _kro_cluster("acme-keep", resourcePrefix=PREFIX, deletionPolicy="retain"),
        "other-spoke/other-spoke": _kro_cluster("other-spoke", resourcePrefix="other"),
    }
    cmds, tvars = _disable_all()
    res, events, st = _run(tmp_path, cmds, tvars, {
        "git_fails": True, "crds": ["eksclusterwithvpcs.kro.run"],
        "objs": {"eksclusterwithvpcs.kro.run": kro}, "eks_live": []})
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "discovering spokes on the hub" in out, out
    assert "Could not resolve host" in out, out          # the clone error is printed ...
    assert SECRET not in out and "user1:" not in out, out  # ... with the credentials redacted
    deleted = sorted(e[3] for e in events if e[0] == "delete")
    assert deleted == ["acme-spoke-dev", "acme-spoke-prod"], deleted
    assert "Sparing kro spoke acme-keep" in out, out
    assert "nothing to tear down" not in out


def test_p2_hub_fallback_crossplane_claims(tmp_path):
    xp = {
        f"crossplane-system/{HUB}": _obj("pc", "crossplane-system", HUB, clusterName=HUB),
        "crossplane-system/acme-spoke-dev": _obj("pc", "crossplane-system", "acme-spoke-dev",
                                                 clusterName="acme-spoke-dev", resourcePrefix=PREFIX),
    }
    cmds, tvars = _disable_all()
    res, events, _ = _run(tmp_path, cmds, tvars, {
        "git_fails": True, "crds": ["platformclusters.platform.gitops.io"],
        "objs": {"platformclusters.platform.gitops.io": xp}})
    assert res.returncode == 0, res.stdout + res.stderr
    assert [e[3] for e in events if e[0] == "delete"] == ["acme-spoke-dev"]


def test_p2_hub_fallback_waits_for_spokes_in_aws(tmp_path):
    cmds, tvars = _disable_all()
    kro = {"acme-spoke-dev/acme-spoke-dev": _kro_cluster("acme-spoke-dev", resourcePrefix=PREFIX)}
    res, events, _ = _run(tmp_path, cmds, tvars, {
        "git_fails": True, "crds": ["eksclusterwithvpcs.kro.run"],
        "objs": {"eksclusterwithvpcs.kro.run": kro}, "eks_live": ["acme-spoke-dev"]})
    assert res.returncode == 0, res.stdout + res.stderr
    polls = [e for e in events if e[0] == "aws" and e[1][:2] == ["eks", "describe-cluster"]]
    assert polls and all("acme-spoke-dev" in e[1] for e in polls)
    assert "still present after wait" in res.stdout + res.stderr


def test_p2_nothing_on_hub_says_so_loudly(tmp_path):
    cmds, tvars = _disable_all()
    res, events, _ = _run(tmp_path, cmds, tvars, {"git_fails": True, "crds": []})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "No spoke found on the hub either" in res.stdout + res.stderr


# ------------------------------------------------------------------ phase markers

PHASES = ["0 kubeconfig", "1 drain", "1b app-layer", "2 spokes", "2.5 devlake-rds", "3 hub", "done"]


def test_every_phase_has_a_best_effort_marker():
    cmds = [_cmd_text(c) for c in _destroy_cmds()]
    marks = [c for c in cmds if c.startswith("{{.DESTROY_MARK}}")]
    assert [re.search(r'"([^"$]+) \$\(date', m).group(1) for m in marks] == PHASES, marks
    for m in marks:
        assert m.rstrip().endswith("|| true"), m
    v = _taskfile()["tasks"]["destroy"]["vars"]
    assert v["DESTROY_PHASE_PARAM"] == "/{{.RESOURCE_PREFIX}}/destroy-phase"
    assert "put-parameter" in v["DESTROY_MARK"] and "{{.DESTROY_PHASE_PARAM}}" in v["DESTROY_MARK"]
    assert "--cli-connect-timeout" in v["DESTROY_MARK"] and "--cli-read-timeout" in v["DESTROY_MARK"]
    # Each marker comes right before its phase's first command.
    for i, c in enumerate(cmds):
        if c.startswith("{{.DESTROY_MARK}}") and "done" not in c:
            assert "Phase" in cmds[i + 1] or "aws eks update-kubeconfig" in cmds[i + 1], cmds[i + 1]


@pytest.mark.parametrize("aws_rc", [0, 255])
def test_marker_never_fails_the_destroy(tmp_path, aws_rc):
    mark = next(c for c in _destroy_cmds() if _cmd_text(c).startswith('{{.DESTROY_MARK}} "2 spokes'))
    v = _p25_vars()
    res, events, _ = _run(tmp_path, [mark, "echo AFTER"], v, {"crds": [], "aws_rc": aws_rc})
    assert res.returncode == 0 and "AFTER" in res.stdout, res.stdout + res.stderr
    put = [e[1] for e in events if e[0] == "aws" and e[1][:2] == ["ssm", "put-parameter"]]
    assert put, events
    a = put[0]
    assert a[a.index("--name") + 1] == f"/{PREFIX}/destroy-phase"
    assert re.fullmatch(r"2 spokes \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", a[a.index("--value") + 1]), a


# ------------------------------------------------------------------ errexit traps

AND_STMT = re.compile(r"^\s*\[\[? .*\]\]?\s*&&")


def test_no_statement_level_and_lists_in_changed_blocks():
    blocks = [_cmd_text(_phase25_cmd())] + [_cmd_text(c) for c in _disable_all()[0]]
    bad = [line.strip() for b in blocks for line in b.splitlines()
           if AND_STMT.match(line) and not line.strip().startswith("#")]
    assert not bad, "statement-level `[ ] && cmd` (errexit trap):\n" + "\n".join(bad)
