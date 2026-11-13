"""Hermetic tests for the minimal hub:pivot kind-stop fix, run through REAL go-task (mvdan/sh).

Regression: `docker stop` on the kind node can fail ("did not receive an exit event") while the
node does stop. KIND_STOPPED=1 was set only after the stop, so the EXIT trap did not restart kind
and workshop/Taskfile.yaml printed "restarted kind" regardless. The hub:pivot shell block and the
workshop pivot step are read verbatim from the Taskfiles, their go-task variables are filled in,
and each is executed by the `task` binary (set: errexit/nounset/pipefail, like the real
Taskfiles) against fake docker/kubectl/aws on PATH. Executing with plain bash would hide
go-task-specific shell behaviour (for example `return` inside EXIT-trap functions).

Run:  python -m pytest workshop/scripts/tests/test_hub_pivot_kind_stop.py -q
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
for tool in ("bash", "jq", "task"):
    if not shutil.which(tool):
        pytest.skip(f"{tool} not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROVIDER_TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
WORKSHOP_TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")
DOCKER_EXIT_EVENT_ERR = ("Error response from daemon: cannot stop container: kindnode1: tried to kill "
                         "container, but did not receive an exit event")
HUB = "acme-hub"
KIND = "acme-hub-bootstrap"

# --- fakes -------------------------------------------------------------------------------

FAKE_DOCKER = r'''#!{python} -I
import json, os, sys
ST, LOG = os.environ["FAKE_STATE"], os.environ["FAKE_LOG"]
s = json.load(open(ST))
a = sys.argv[1:]
open(LOG, "a").write("docker " + " ".join(a) + "\n")
def save(): json.dump(s, open(ST, "w"))
nodes = s["nodes"]
if a[0] == "ps":
    # docker unreachable: always, or only once a stop was attempted
    if s.get("ps") == "fail" or (s.get("ps") == "fail-after-stop" and s.get("stop_called")):
        print("Cannot connect to the Docker daemon", file=sys.stderr); sys.exit(1)
    # --filter label=io.x-k8s.kind.cluster=<name> must match the node's label (a wrong name lists nothing)
    want = [x.split("=", 2)[2] for x in a if x.startswith("label=io.x-k8s.kind.cluster=")]
    if want and want[0] != s.get("label", {kind!r}):
        sys.exit(0)
    print("\n".join(n for n in nodes if nodes[n])); sys.exit(0)
ids = [x for x in a[1:] if x in nodes]
mode = s.get(a[0], "ok")
if a[0] in ("stop", "kill"):
    s["stop_called"] = True
    if mode in ("ok", "err-stops"):
        for n in ids: nodes[n] = False
    save()
    if mode.startswith("err"):
        print({err!r}, file=sys.stderr); sys.exit(1)
    sys.exit(0)
if a[0] == "start":
    if mode == "ok":
        for n in ids: nodes[n] = True
        save(); print("\n".join(ids)); sys.exit(0)
    print("Error response from daemon: failed to start", file=sys.stderr); sys.exit(1)
sys.exit(0)
'''

FAKE_KUBECTL = r'''#!{python} -I
import json, os, sys
ST, LOG = os.environ["FAKE_STATE"], os.environ["FAKE_LOG"]
s = json.load(open(ST))
raw = sys.argv[1:]
a = [x.lower() for x in raw]
kc = os.environ.get("KUBECONFIG", "")
side = "kind" if kc.endswith("kind-kubeconfig") else "hub"
open(LOG, "a").write("kubectl[%s] %s\n" % (side, " ".join(raw)))
def save(): json.dump(s, open(ST, "w"))
if side == "kind":
    if not s["nodes"] or not all(s["nodes"].values()):
        print("The connection to the server was refused", file=sys.stderr); sys.exit(1)
    if not s.get("kind_instance", True) and "ekscluster.kro.run" in a and "get" in a:
        sys.exit(1)
    if "get" in a and "ekscluster.kro.run" in a and "json" in a:
        print(json.dumps({{"apiVersion": "kro.run/v1alpha1", "kind": "EksCluster",
            "metadata": {{"name": "{hub}", "namespace": "{hub}", "finalizers": ["x"]}},
            "spec": {{"name": "{hub}", "deletionPolicy": "delete"}}}})); sys.exit(0)
    if "cluster.eks.services.k8s.aws" in a and "json" in a:
        print("{{}}"); sys.exit(0)
    if any("deletion-policy" in x for x in a) and "get" in a:
        print("retain"); sys.exit(0)
    sys.exit(0)
# hub side
if "get" in a and "ekscluster.kro.run" in a and "{hub}" in a:
    if not s.get("hub_adopted"): sys.exit(1)
    if any("status.state" in x for x in a): print("ACTIVE")
    sys.exit(0)
if "apply" in a and "-f" in a:
    f = raw[a.index("-f") + 1]
    if f == "-":
        sys.stdin.read(); sys.exit(0)
    if s.get("hub_apply_fails"):
        print("error: hub apply failed", file=sys.stderr); sys.exit(1)
    s["hub_adopted"] = True; save(); sys.exit(0)
if "create" in a and "namespace" in a:
    print("apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {hub}"); sys.exit(0)
if "delete" in a and "ekscluster.kro.run" in a:
    s["hub_adopted"] = False; save(); sys.exit(0)
sys.exit(0)
'''

FAKE_AWS = r'''#!{python} -I
import json, os, sys
open(os.environ["FAKE_LOG"], "a").write("aws " + " ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if "describe-cluster" in a and json.load(open(os.environ["FAKE_STATE"])).get("describe_cluster_fails"):
    sys.exit(255)
if "describe-capability" in a or "describe-cluster" in a:
    print("ACTIVE")
sys.exit(0)
'''


def _write_exe(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def ctx(tmp_path):
    bindir = tmp_path / "bin"; bindir.mkdir()
    fmt = dict(python=sys.executable, err=DOCKER_EXIT_EVENT_ERR, hub=HUB, kind=KIND)
    _write_exe(bindir / "docker", FAKE_DOCKER.format(**fmt))
    _write_exe(bindir / "kubectl", FAKE_KUBECTL.format(**fmt))
    _write_exe(bindir / "aws", FAKE_AWS.format(**fmt))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"nodes": {"kindnode1": True}}))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(state),
               FAKE_LOG=str(tmp_path / "calls.log"), TMPDIR=str(tmp_path),
               )
    return {"tmp": tmp_path, "env": env, "state": state}


def set_state(ctx, **kw):
    s = json.loads(ctx["state"].read_text()); s.update(kw)
    ctx["state"].write_text(json.dumps(s))


def get_state(ctx):
    return json.loads(ctx["state"].read_text())


def calls(ctx):
    p = ctx["tmp"] / "calls.log"
    return p.read_text().splitlines() if p.exists() else []



def run_task(ctx, script, name="p"):
    """Execute `script` as a go-task cmd (real mvdan/sh), like the real Taskfiles do."""
    d = ctx["tmp"] / ("tf-" + name); d.mkdir(exist_ok=True)
    (d / "Taskfile.yml").write_text(json.dumps({
        "version": "3", "set": ["errexit", "nounset", "pipefail"],
        "tasks": {name: {"cmds": [{"cmd": script}]}}}))
    return subprocess.run(["task", "-s", "-d", str(d), name], env=ctx["env"], capture_output=True,
                          text=True, timeout=120)


def render(script, values):
    script = re.sub(r'\{\{if eq \.([A-Z_]+) "([^"]*)"\}\}(.*?)\{\{else\}\}(.*?)\{\{end\}\}',
                    lambda m: m.group(3) if values.get(m.group(1)) == m.group(2) else m.group(4), script)
    script = re.sub(r"\{\{\s*\.([A-Z0-9_]+)\s*\}\}", lambda m: values[m.group(1)], script)
    assert "{{" not in script, re.findall(r"\{\{[^}]*\}\}", script)
    return script


def run_pivot(ctx):
    cmds = yaml.safe_load(open(PROVIDER_TASKFILE))["tasks"]["hub:pivot"]["cmds"]
    script = next(c for c in cmds if isinstance(c, str) and "hub:pivot (" in c)
    t = ctx["tmp"]
    values = {
        "HUB_CLUSTER_NAME": HUB, "KIND_CLUSTER_NAME": KIND, "AWS_REGION": "us-west-2",
        "KINDKC": str(t / "kind-kubeconfig"), "HUBKC": str(t / "hub-kubeconfig"),
        "HUB_KIND": "EksCluster", "ROOT_DIR": REPO, "PIVOT_DRY_RUN": "false", "PIVOT_CONFIRM": "yes",
        "PIVOT_DETACH_MODE": "stop", "PIVOT_ADOPT_TIMEOUT_SEC": "5", "PIVOT_ADOPT_INTERVAL_SEC": "0",
        "HUB_PIVOT_GITOPS": "false", "C_STEP": "", "C_OK": "", "C_ERR": "", "C_INFO": "", "C_RESET": "",
    }
    script = render(script, values).replace("sleep 5\n", "sleep 0\n").replace("sleep 2", "sleep 0")
    return run_task(ctx, script)


def kind_running(ctx):
    n = get_state(ctx)["nodes"]
    return bool(n) and all(n.values())


def test_stop_error_but_stopped_still_adopts(ctx):
    set_state(ctx, stop="err-stops")
    r = run_pivot(ctx)
    assert r.returncode == 0, r.stdout + r.stderr
    assert get_state(ctx)["hub_adopted"] is True
    assert not kind_running(ctx)  # intentionally detached (PIVOT_DETACH_MODE=stop)


def test_failure_after_stop_error_restarts_kind(ctx):
    # The event: docker stop errors although the node stops; a later step then fails.
    # The EXIT trap must restart kind (on main it did not: KIND_STOPPED was still 0).
    set_state(ctx, stop="err-stops", hub_apply_fails=True)
    r = run_pivot(ctx)
    assert r.returncode != 0
    assert kind_running(ctx), r.stdout + r.stderr
    assert any(c.startswith("docker start") for c in calls(ctx))


def test_stop_that_never_completes_aborts_and_restarts_kind(ctx):
    # docker stop fails and the node keeps running, even after docker kill: abort, kind stays up.
    set_state(ctx, stop="err-hangs", kill="err-hangs")
    r = run_pivot(ctx)
    assert r.returncode != 0
    assert "after docker kill" in r.stdout + r.stderr
    assert kind_running(ctx)
    assert get_state(ctx).get("hub_adopted") is not True


def test_stop_ignored_then_kill_succeeds(ctx):
    set_state(ctx, stop="noop")
    r = run_pivot(ctx)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(c.startswith("docker kill") for c in calls(ctx))
    assert get_state(ctx)["hub_adopted"] is True


def test_docker_ps_failure_after_stop_error_never_adopts(ctx):
    # B1: a failing `docker ps` is "unknown", never "stopped". Stop fails, the node keeps
    # running, and ps then fails: the hub must NOT adopt while kind runs.
    set_state(ctx, stop="err-hangs", kill="err-hangs", ps="fail-after-stop")
    r = run_pivot(ctx)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "docker state unknown" in out
    assert get_state(ctx).get("hub_adopted") is not True
    assert "adopting on hub" not in out
    assert kind_running(ctx)


def test_docker_ps_failure_when_the_stop_worked_still_aborts_and_restarts_kind(ctx):
    # The node did stop, but we cannot confirm it (ps fails): fail closed, the trap restarts kind.
    set_state(ctx, stop="err-stops", ps="fail-after-stop")
    r = run_pivot(ctx)
    assert r.returncode != 0
    assert get_state(ctx).get("hub_adopted") is not True
    assert any(c.startswith("docker start") for c in calls(ctx))
    assert kind_running(ctx)


def test_docker_ps_failure_before_the_stop_touches_nothing(ctx):
    set_state(ctx, ps="fail")
    r = run_pivot(ctx)
    assert r.returncode != 0
    assert "cannot list the kind nodes" in r.stdout + r.stderr
    assert not any(c.startswith(("docker stop", "docker kill", "docker start")) for c in calls(ctx))
    assert kind_running(ctx) and get_state(ctx).get("hub_adopted") is not True


def test_post_detach_eks_check_failure_does_not_advise_starting_kind(ctx):
    # C1: detach is committed (hub owns the resources, kind stopped on purpose). A failing
    # describe-cluster must be reported as such, never as a kind-down failure.
    set_state(ctx, describe_cluster_fails=True)
    r = run_pivot(ctx)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    warn = next(l for l in out.splitlines() if "EKS status check returned" in l)
    assert "Do NOT start kind" in warn and "docker start" not in warn
    assert get_state(ctx)["hub_adopted"] is True and not kind_running(ctx)


def test_fake_docker_honours_the_label_filter(ctx):
    # C2: guards the fake itself, so a wrong label in the Taskfile cannot go unnoticed.
    ok = subprocess.run(["docker", "ps", "-q", "--filter", f"label=io.x-k8s.kind.cluster={KIND}"],
                        env=ctx["env"], capture_output=True, text=True)
    wrong = subprocess.run(["docker", "ps", "-q", "--filter", "label=io.x-k8s.kind.cluster=WRONG"],
                           env=ctx["env"], capture_output=True, text=True)
    assert ok.stdout.split() == ["kindnode1"] and wrong.stdout.strip() == ""


def test_kind_stopped_flag_is_set_before_the_stop():
    cmds = yaml.safe_load(open(PROVIDER_TASKFILE))["tasks"]["hub:pivot"]["cmds"]
    s = next(c for c in cmds if isinstance(c, str) and "hub:pivot (" in c)
    assert s.index("KIND_STOPPED=1\n") < s.index("docker stop -t 30")


# --- workshop install step ------------------------------------------------------------------

def run_workshop(ctx, task_rc):
    cmds = yaml.safe_load(open(WORKSHOP_TASKFILE))["tasks"]["install"]["cmds"]
    steps = [c["cmd"] for c in cmds if isinstance(c, dict) and "hub:pivot" in c.get("cmd", "")]
    assert len(steps) == 1
    t = ctx["tmp"]
    import time
    values = {"PROVIDER": "kind-kro-ack", "PLATFORM_DIR": str(t), "HUB_CLUSTER_NAME": HUB,
              "INSTALL_START": str(int(time.time()) - 600),
              "C_STEP": "", "C_OK": "", "C_ERR": "", "C_INFO": "", "C_RESET": ""}
    tv = re.compile(r'\{\{\s*\.([A-Z0-9_]+)\s*(?:\|\s*default\s+\.([A-Z0-9_]+)\s*)?'
                    r'(?:\|\s*default\s+"([^"]*)"\s*)?\}\}')
    def fill(m):
        n, fb, d = m.group(1), m.group(2), m.group(3)
        if values.get(n): return values[n]
        if fb and values.get(fb): return values[fb]
        return d if d is not None else ""
    script = tv.sub(fill, steps[0])
    bindir = t / "bin"
    fake_task = bindir / "task"  # shadows the real task ONLY for the inner pivot call
    real_task = shutil.which("task")
    body = f'#!/usr/bin/env bash\nif [ "$1" = kind-kro-ack:hub:pivot ] || [[ "$*" == *hub:pivot* ]]; then exit {task_rc}; fi\nexec {real_task} "$@"\n'
    fake_task.write_text(body); fake_task.chmod(fake_task.stat().st_mode | stat.S_IEXEC)
    return run_task(ctx, script, "w")


def test_workshop_says_kind_running_only_when_it_is(ctx):
    r = run_workshop(ctx, task_rc=1)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "kind running" in r.stdout and "kind is NOT running" not in r.stdout
    assert "the pivot fail-closed and restarted kind" not in r.stdout


def test_workshop_is_loud_when_kind_is_down(ctx):
    set_state(ctx, nodes={"kindnode1": False})
    r = run_workshop(ctx, task_rc=1)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "kind is NOT running" in r.stdout
    assert f"docker start $(docker ps -aq --filter label=io.x-k8s.kind.cluster={KIND})" in r.stdout
    assert "restarted kind" not in r.stdout


def test_workshop_success_message(ctx):
    r = run_workshop(ctx, task_rc=0)
    assert "hub pivoted" in r.stdout
