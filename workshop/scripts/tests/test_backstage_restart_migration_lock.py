"""Backstage restart after Keycloak config must never leave a duplicated knex migration lock.

`hub:restart-backstage` (cluster-providers/kind-kro-ack/Taskfile.yaml, run by
install:finalize) used to be `kubectl rollout restart ... || true`. Under RollingUpdate it
started a second pod while the first was still migrating a fresh database; both inserted a
row into a `*_knex_migrations_lock` table, and every later start then failed with
MigrationLocked while the pod stayed Running and the catalog stayed empty or 503.

The fix has three parts, all tested here:
  * chart: the Backstage Deployment uses strategy Recreate and runs a
    `dedupe-migration-locks` init container that keeps one row per lock table;
  * scripts/restart-backstage.sh: restart only when the pod predates the Keycloak config,
    wait for the current pod to finish initialising first, then gate on the backend log and
    an authenticated catalog read of the gate template, with one repair restart;
  * the init container's SQL, run for real against Postgres (skipped without docker).

`kubectl` is a fake on PATH that simulates the Deployment, its pods and the lock tables
(state in a JSON file); `sleep` is a no-op. The task's cmds are read from the Taskfile and
run with bash, so `test_task_repairs_duplicated_lock` fails on the old task. No AWS.

Run:  python -m pytest workshop/scripts/tests/test_backstage_restart_migration_lock.py -q
"""
import json
import os
import re
import shutil
import subprocess
import time
import uuid

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "scripts", "restart-backstage.sh")
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
CHART = os.path.join(REPO, "gitops", "addons", "charts", "backstage")
TEMPLATE_VAR = re.compile(r'\{\{\s*\.([A-Z0-9_]+)\s*(?:\|\s*default\s+"([^"]*)"\s*)?\}\}')
KC_DONE = "2026-01-01T10:05:00Z"
BEFORE, AFTER = "2026-01-01T10:04:00Z", "2026-01-01T10:06:00Z"

# Fake kubectl: a tiny simulation of the backstage namespace.
FAKE_KUBECTL = r'''#!/usr/bin/env python3
import json, os, sys
P = os.environ["SIM_STATE"]
s = json.load(open(P))
argv = sys.argv[1:]
s["calls"].append(" ".join(argv))
ns, args, i = None, [], 0
while i < len(argv):
    a = argv[i]
    if a in ("-n", "--namespace"):
        ns = argv[i + 1]; i += 2; continue
    args.append(a); i += 1
out, rc = "", 0

def save():
    json.dump(s, open(P, "w"))

def pod(name):
    return next((p for p in s["pods"] if p["name"] == name), None)

def logs(p):
    if p["phase"] == "failed":
        return "Plugin initialization started\nBackend startup failed MigrationLocked: Migration table is already locked\n"
    if p["phase"] == "initialized":
        return "Plugin initialization started\nPlugin initialization complete, newly initialized: catalog\n"
    return "Plugin initialization started\n"

def new_pod():
    s["seq"] += 1
    if "dedupe-migration-locks" in s["init_containers"]:
        fixed = [t for t, n in s["locks"].items() if n > 1]
        for t in fixed:
            s["locks"][t] = 1
        s["dedupe_log"] = "dedupe-migration-locks: %d table(s) repaired" % len(fixed)
    broken = s["always_fail"] or any(n > 1 for n in s["locks"].values())
    return {"name": "backstage-%d" % s["seq"], "start": "2026-01-01T11:%02d:00Z" % s["seq"],
            "deleting": False, "phase": "failed" if broken else "initialized",
            "polls_to_init": 0}

if args[:3] == ["get", "deploy", "backstage"]:
    if not s["deploy"] and s["deploy_after"] > 0:
        # The Argo CD app syncs the Deployment a few polls later (late sync wave).
        s["deploy_after"] -= 1
        if s["deploy_after"] == 0:
            s["deploy"] = True
            s["pods"] = [dict(s["appearing_pod"])]
    if not s["deploy"]:
        rc = 1
    elif any("strategy.type" in a for a in args):
        out = s["strategy"]
    else:
        out = "backstage"
elif args[:2] == ["get", "pods"]:
    out = "".join("%s|%s|%s\n" % (p["name"], "2026-01-01T00:00:00Z" if p["deleting"] else "", p["start"])
                  for p in s["pods"])
elif args[:2] == ["get", "pod"]:
    p = pod(args[2])
    out = "True" if p and p["phase"] == "initialized" else "False"
elif args[:1] == ["get"] and args[1] == "application.argoproj.io":
    if args[2].startswith("backstage-"):
        rc = 0 if s["backstage_app"] else 1
        out = args[2] if s["backstage_app"] else ""
    else:
        out = s["kc_finished"]
elif args[:2] == ["get", "secret"]:
    out = s["hub_labels"].get("enable_backstage", "")
elif args[:1] == ["logs"]:
    p = pod(args[1])
    if p is None:
        rc = 1
    elif args[-1] == "dedupe-migration-locks":
        out = s.get("dedupe_log", "") + "\n"
    else:
        out = logs(p)
        if p["phase"] == "starting":
            p["polls_to_init"] -= 1
            if p["polls_to_init"] <= 0:
                p["phase"] = "initialized"
elif args[:1] == ["exec"]:
    p = pod(args[1])
    path = args[-1]
    s["catalog_paths"].append(path)
    ok = p and p["phase"] == "initialized" and (s["template_present"] or "by-name" not in path)
    out = "200\n" if ok else "503\n"
elif args[:1] == ["patch"]:
    s["strategy"] = "Recreate"
elif args[:2] == ["rollout", "restart"]:
    old = [dict(p) for p in s["pods"]]
    s["restarts"].append({"strategy": s["strategy"], "old": [(p["name"], p["phase"]) for p in old]})
    if s["strategy"] != "Recreate" and any(p["phase"] == "starting" for p in old):
        # RollingUpdate: the new pod starts its first boot while the old one is still
        # migrating; each inserts a lock row.
        for t in s["locks"]:
            s["locks"][t] = 2
        for p in s["pods"]:
            p["phase"] = "failed"
    s["pods"] = [new_pod()]
elif args[:2] == ["rollout", "status"]:
    pass
else:
    sys.stderr.write("fake kubectl: unexpected call %r\n" % argv); rc = 1
save()
sys.stdout.write(out)
sys.exit(rc)
'''


def _state(**over):
    st = {"deploy": True, "strategy": "Recreate", "init_containers": _chart_init_containers(),
          "kc_finished": KC_DONE, "locks": {"backstage_plugin_proxy.lock": 1},
          "pods": [{"name": "backstage-0", "start": BEFORE, "deleting": False,
                    "phase": "initialized", "polls_to_init": 0}],
          "seq": 0, "always_fail": False, "template_present": True,
          "calls": [], "restarts": [], "catalog_paths": [],
          "backstage_app": True, "hub_labels": {"enable_backstage": "true"}, "deploy_after": 0,
          "appearing_pod": {"name": "backstage-new", "start": AFTER, "deleting": False,
                            "phase": "starting", "polls_to_init": 2}}
    st.update(over)
    return st


def _env(tmp_path, state):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "kubectl").write_text(FAKE_KUBECTL)
    (bindir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for f in ("kubectl", "sleep"):
        (bindir / f).chmod(0o755)
    sim = tmp_path / "state.json"
    sim.write_text(json.dumps(state))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", SIM_STATE=str(sim),
               KUBECONFIG=str(tmp_path / "kubeconfig"))
    for k in ("GATE_TEMPLATE", "KEYCLOAK_APP", "WAIT_INIT_TIMEOUT", "GATE_TIMEOUT", "BACKSTAGE_APP",
              "HUB_CLUSTER_SECRET", "WAIT_DEPLOY_TIMEOUT", "BACKSTAGE_GATE_WAIT", "BACKSTAGE_GATE_LOG"):
        env.pop(k, None)
    return env, sim


def _run_script(tmp_path, state, *args, **extra):
    env, sim = _env(tmp_path, state)
    env.update(KEYCLOAK_APP="keycloak-acme-hub", BACKSTAGE_APP="backstage-acme-hub",
               HUB_CLUSTER_SECRET="acme-hub", **extra)
    res = subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True, timeout=60)
    return res, json.loads(sim.read_text())


def _chart_deployment():
    if not shutil.which("helm"):
        return None
    out = subprocess.run(["helm", "template", "t", CHART, "--set", "backstage_image=example/backstage:1",
                          "--set", "global.aws_cluster_name=acme-hub"],
                         capture_output=True, text=True, check=True).stdout
    return next(d for d in yaml.safe_load_all(out)
                if d and d["kind"] == "Deployment" and d["metadata"]["name"] == "backstage")


def _chart_init_containers():
    """Init container names of the chart's Backstage Deployment (read from the template
    text, so the simulation follows the chart even without helm)."""
    text = open(os.path.join(CHART, "templates", "install.yaml")).read()
    dep = text[text.index("kind: Deployment\nmetadata:\n  name: backstage\n"):]
    dep = dep[:dep.index("\n---")]
    init = dep[dep.index("initContainers:"):dep.index("\n      containers:")]
    return re.findall(r"^        - name: ([a-z0-9-]+)$", init, re.M)


# ── chart ─────────────────────────────────────────────────────────────────────

def test_chart_deployment_is_recreate_with_dedupe_init_container():
    dep = _chart_deployment()
    if dep is None:
        pytest.skip("helm not on PATH")
    assert dep["spec"]["strategy"] == {"type": "Recreate"}
    inits = [c["name"] for c in dep["spec"]["template"]["spec"]["initContainers"]]
    assert inits[-1] == "dedupe-migration-locks", inits
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in
           dep["spec"]["template"]["spec"]["initContainers"][-1]["env"] if "valueFrom" in e}
    assert env["PGPASSWORD"] == {"name": "backstage-postgres-vars", "key": "POSTGRES_PASSWORD"}
    assert {"PGHOST", "PGPORT", "PGUSER", "PGDATABASE"} <= set(env)


# ── restart-backstage.sh ──────────────────────────────────────────────────────

def test_pod_started_after_keycloak_is_not_restarted(tmp_path):
    st = _state(pods=[{"name": "backstage-0", "start": AFTER, "deleting": False,
                       "phase": "initialized", "polls_to_init": 0}])
    res, out = _run_script(tmp_path, st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert out["restarts"] == [] and "restart not needed" in res.stdout
    assert "gate passed" in res.stdout


def test_restart_waits_for_current_pod_to_finish_init(tmp_path):
    st = _state(strategy="RollingUpdate",
                pods=[{"name": "backstage-0", "start": BEFORE, "deleting": False,
                       "phase": "starting", "polls_to_init": 3}])
    res, out = _run_script(tmp_path, st)
    assert res.returncode == 0, res.stdout + res.stderr
    (r,) = out["restarts"]
    # restarted only once the first pod had finished initialising, and under Recreate
    assert r["old"] == [("backstage-0", "initialized")] or r["old"] == [["backstage-0", "initialized"]]
    assert r["strategy"] == "Recreate"
    assert any(c.startswith("-n backstage patch deploy backstage") for c in out["calls"])
    assert out["locks"] == {"backstage_plugin_proxy.lock": 1}


def test_duplicated_lock_is_repaired_by_the_restart(tmp_path):
    st = _state(locks={"backstage_plugin_proxy.lock": 2, "backstage_plugin_catalog.lock": 1},
                pods=[{"name": "backstage-0", "start": BEFORE, "deleting": False,
                       "phase": "failed", "polls_to_init": 0}])
    res, out = _run_script(tmp_path, st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert len(out["restarts"]) == 1
    assert set(out["locks"].values()) == {1}
    assert out["pods"][0]["phase"] == "initialized"


def test_broken_pod_after_keycloak_gets_one_repair_restart(tmp_path):
    st = _state(locks={"backstage_plugin_proxy.lock": 2},
                pods=[{"name": "backstage-0", "start": AFTER, "deleting": False,
                       "phase": "failed", "polls_to_init": 0}])
    res, out = _run_script(tmp_path, st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert len(out["restarts"]) == 1
    assert "gate failed" in res.stdout and "MigrationLocked" in res.stdout
    assert "1 table(s) repaired" in res.stdout and "recovered" in res.stdout


def test_persistent_failure_fails_loud_after_one_repair(tmp_path):
    st = _state(always_fail=True)
    res, out = _run_script(tmp_path, st)
    assert res.returncode == 1
    assert len(out["restarts"]) == 2  # the R1 restart + exactly one repair restart
    assert "not healthy after one repair restart" in res.stderr
    assert "MigrationLocked" in res.stderr


def test_missing_gate_template_fails_loud(tmp_path):
    st = _state(template_present=False,
                pods=[{"name": "backstage-0", "start": AFTER, "deleting": False,
                       "phase": "initialized", "polls_to_init": 0}])
    res, out = _run_script(tmp_path, st, GATE_TIMEOUT="30")
    assert res.returncode == 1
    assert len(out["restarts"]) == 1
    assert "HTTP 503" in res.stderr
    assert all(p.endswith("/backstage/api/catalog/entities/by-name/template/default/cicd-pipeline-gitops")
               for p in out["catalog_paths"]), out["catalog_paths"]


def test_catalog_read_is_authenticated_inside_the_pod(tmp_path):
    res, out = _run_script(tmp_path, _state(pods=[{"name": "backstage-0", "start": AFTER,
                                                  "deleting": False, "phase": "initialized",
                                                  "polls_to_init": 0}]))
    assert res.returncode == 0, res.stderr
    (call,) = [c for c in out["calls"] if c.startswith("-n backstage exec")]
    assert "-c backstage -- node -e" in call and "Bearer" in call and "BACKEND_SECRET" in call


def test_no_backstage_is_an_honest_skip(tmp_path):
    """Not installed (no Deployment, no Argo CD app, no hub label): exit 3, never 0, so the
    task cannot report a healthy Backstage that was never checked."""
    st = _state(deploy=False, backstage_app=False, hub_labels={}, pods=[])
    res, out = _run_script(tmp_path, st)
    assert res.returncode == 3, res.stdout + res.stderr
    assert out["restarts"] == [] and out["catalog_paths"] == []
    assert "Backstage not installed: skipped" in res.stdout
    assert "gate passed" not in res.stdout


def test_probe_reports_present_expected_absent(tmp_path):
    cases = [(_state(), "present"),
             (_state(deploy=False, pods=[]), "expected"),
             (_state(deploy=False, pods=[], backstage_app=False), "expected"),  # hub label only
             (_state(deploy=False, pods=[], hub_labels={}), "expected"),        # app only
             (_state(deploy=False, pods=[], backstage_app=False, hub_labels={}), "absent")]
    for i, (st, want) in enumerate(cases):
        d = tmp_path / str(i); d.mkdir()
        res, out = _run_script(d, st, "probe")
        assert res.returncode == 0 and res.stdout.strip() == want, (want, res.stdout, res.stderr)
        assert out["restarts"] == [] and out["catalog_paths"] == []


def test_deploy_appearing_later_is_waited_for_and_gated(tmp_path):
    """Live finding: the task ran at 15:23, the Deployment appeared at 15:32. The script
    must wait for it, then run the restart decision and the gate (it used to exit 0 with
    'nothing to restart')."""
    st = _state(deploy=False, pods=[], deploy_after=4)
    res, out = _run_script(tmp_path, st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "waiting for deploy/backstage" in res.stdout
    assert "restart not needed" in res.stdout  # its pod started after Keycloak
    assert out["restarts"] == []
    assert "gate passed" in res.stdout and out["catalog_paths"], res.stdout


def test_deploy_appearing_with_a_stale_pod_is_restarted_then_gated(tmp_path):
    st = _state(deploy=False, pods=[], deploy_after=2,
                appearing_pod={"name": "backstage-early", "start": BEFORE, "deleting": False,
                               "phase": "initialized", "polls_to_init": 0})
    res, out = _run_script(tmp_path, st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert len(out["restarts"]) == 1 and "gate passed" in res.stdout


def test_expected_deploy_that_never_appears_fails_loud(tmp_path):
    st = _state(deploy=False, pods=[], backstage_app=False)  # hub label says enabled
    res, out = _run_script(tmp_path, st, WAIT_DEPLOY_TIMEOUT="60")
    assert res.returncode == 1
    assert "did not appear within 60s" in res.stderr
    assert "gate passed" not in res.stdout


def test_unknown_keycloak_time_restarts(tmp_path):
    res, out = _run_script(tmp_path, _state(kc_finished=""))
    assert res.returncode == 0, res.stderr
    assert len(out["restarts"]) == 1


# ── the task itself (fails on the old `rollout restart || true`) ──────────────

def _task_cmds():
    task = yaml.safe_load(open(TASKFILE))["tasks"]["hub:restart-backstage"]
    values = {"ROOT_DIR": REPO, "HUB_CLUSTER_NAME": "acme-hub",
              "C_STEP": "", "C_OK": "", "C_RESET": "", "C_INFO": "", "C_WARN": "", "C_ERR": ""}
    for name, spec in (task.get("vars") or {}).items():
        m = TEMPLATE_VAR.fullmatch(spec.strip()) if isinstance(spec, str) else None
        values[name] = (m.group(2) if m else spec)

    def fill(text):
        out = TEMPLATE_VAR.sub(lambda m: values.get(m.group(1), m.group(2) or ""), text)
        assert "{{" not in out, out
        return out

    cmds, defers = [], []
    for c in task["cmds"]:
        if isinstance(c, str):
            cmds.append(fill(c))
        elif "defer" in c:
            defers.append(fill(c["defer"]))
        elif "cmd" in c:
            cmds.append(fill(c["cmd"]))
    return cmds, defers


HUB_KC = os.path.join(REPO, "private", "hub-kubeconfig")


@pytest.fixture
def hub_kubeconfig():
    """`task: hub:kubeconfig` is not run here; stand in for its file (private/ is gitignored)."""
    os.makedirs(os.path.dirname(HUB_KC), exist_ok=True)
    created = not os.path.exists(HUB_KC)
    if created:
        open(HUB_KC, "w").write("# test stand-in\n")
    yield
    if created and os.path.exists(HUB_KC):
        os.remove(HUB_KC)


def _run_task(tmp_path, state, **extra):
    env, sim = _env(tmp_path, state)
    env.update(INSTALL_TIMING_LOG=str(tmp_path / "timing.log"),
               BACKSTAGE_GATE_LOG=str(tmp_path / "gate.log"), **extra)
    cmds, defers = _task_cmds()
    rc, output = 0, ""
    for c in cmds:  # go-task stops at the first failing cmd
        r = subprocess.run(["bash", "-c", c], env=env, capture_output=True, text=True, timeout=60)
        output += r.stdout + r.stderr
        if r.returncode:
            rc = r.returncode
            break
    for d in defers:
        assert "rm -f" in d  # only the kubeconfig cleanup; do not touch the repo
    return rc, json.loads(sim.read_text()), output


def test_task_repairs_duplicated_lock(tmp_path):
    """On main the task restarts under RollingUpdate with no init repair and `|| true`:
    the lock stays duplicated, Backstage stays broken, and the task still succeeds."""
    st = _state(locks={"backstage_plugin_proxy.lock": 2},
                pods=[{"name": "backstage-0", "start": BEFORE, "deleting": False,
                       "phase": "failed", "polls_to_init": 0}])
    rc, out, _ = _run_task(tmp_path, st)
    assert rc == 0
    assert out["locks"] == {"backstage_plugin_proxy.lock": 1}
    assert [p["phase"] for p in out["pods"]] == ["initialized"]


def test_task_never_overlaps_first_boot(tmp_path):
    """A restart issued while the first pod is still migrating must not duplicate the lock."""
    st = _state(strategy="RollingUpdate",
                pods=[{"name": "backstage-0", "start": BEFORE, "deleting": False,
                       "phase": "starting", "polls_to_init": 2}])
    rc, out, _ = _run_task(tmp_path, st)
    assert rc == 0
    assert out["locks"] == {"backstage_plugin_proxy.lock": 1}
    assert all(r["strategy"] == "Recreate" for r in out["restarts"])


def test_task_fails_when_backstage_stays_broken(tmp_path):
    rc, out, log = _run_task(tmp_path, _state(always_fail=True))
    assert rc != 0
    assert len(out["restarts"]) == 2
    assert "Backstage healthy" not in log


def test_task_says_healthy_only_after_the_gate(tmp_path):
    rc, out, log = _run_task(tmp_path, _state(pods=[{"name": "backstage-0", "start": AFTER,
                                                     "deleting": False, "phase": "initialized",
                                                     "polls_to_init": 0}]))
    assert rc == 0, log
    assert "gate passed" in log and "Backstage healthy" in log
    assert log.index("gate passed") < log.index("Backstage healthy")


def test_task_not_installed_is_an_honest_skip(tmp_path):
    """Fails on the first #1274 revision: it printed 'Backstage healthy' here."""
    st = _state(deploy=False, pods=[], backstage_app=False, hub_labels={})
    rc, out, log = _run_task(tmp_path, st)
    assert rc == 0, log
    assert "Backstage not installed: skipped" in log
    assert "healthy" not in log and out["catalog_paths"] == []


def test_task_foreground_waits_for_the_deployment_then_gates(tmp_path):
    st = _state(deploy=False, pods=[], deploy_after=3)
    rc, out, log = _run_task(tmp_path, st, BACKSTAGE_GATE_WAIT="foreground")
    assert rc == 0, log
    assert "gate passed" in log and out["catalog_paths"]
    assert log.index("gate passed") < log.index("Backstage healthy")


def test_task_foreground_deploy_never_appears_fails(tmp_path):
    st = _state(deploy=False, pods=[])
    rc, out, log = _run_task(tmp_path, st, BACKSTAGE_GATE_WAIT="foreground", WAIT_DEPLOY_TIMEOUT="30")
    assert rc != 0
    assert "did not appear" in log and "healthy" not in log.replace("not healthy", "")


def _wait_for(path, needle, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path) and needle in open(path).read():
            return open(path).read()
        time.sleep(0.2)
    return open(path).read() if os.path.exists(path) else ""


def test_task_background_gate_runs_when_the_deployment_appears(tmp_path, hub_kubeconfig):
    """Default: the install does not wait. The task says the gate is NOT verified yet, and
    the detached job waits for the Deployment, gates, and records the real result."""
    st = _state(deploy=False, pods=[], deploy_after=3)
    rc, _, log = _run_task(tmp_path, st)
    assert rc == 0, log
    assert "NOT verified yet" in log and "Backstage healthy" not in log
    gate_log = _wait_for(tmp_path / "gate.log", "backstage-gate (bg) done")
    assert "gate passed" in gate_log and "✓ Backstage healthy" in gate_log, gate_log
    assert "rc=0" in gate_log
    timing = open(tmp_path / "timing.log").read()
    assert "backstage-gate (bg) start" in timing and "rc=0" in timing
    assert json.loads((tmp_path / "state.json").read_text())["catalog_paths"]
    # the job's kubeconfig copy is cleaned up
    assert not os.path.exists(os.path.join(REPO, "private", "hub-kubeconfig-backstage-gate"))


def test_task_background_gate_failure_is_recorded(tmp_path, hub_kubeconfig):
    st = _state(deploy=False, pods=[], deploy_after=2, always_fail=True,
                appearing_pod={"name": "backstage-new", "start": AFTER, "deleting": False,
                               "phase": "failed", "polls_to_init": 0})
    rc, _, log = _run_task(tmp_path, st)
    assert rc == 0 and "Backstage healthy" not in log
    gate_log = _wait_for(tmp_path / "gate.log", "backstage-gate (bg) done")
    assert "Backstage gate FAILED (rc=1)" in gate_log and "rc=1" in gate_log, gate_log
    assert "Backstage healthy" not in gate_log


def test_task_has_no_silenced_restart():
    text = yaml.safe_load(open(TASKFILE))["tasks"]["hub:restart-backstage"]
    flat = json.dumps(text)
    assert "|| true" not in flat and "rollout restart" not in flat


# ── the init container's SQL, against a real Postgres ─────────────────────────

def _docker_ok():
    return shutil.which("docker") and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.fixture(scope="module")
def postgres():
    if not _docker_ok():
        pytest.skip("docker not available")
    dep = _chart_deployment()
    if dep is None:
        pytest.skip("helm not on PATH")
    init = dep["spec"]["template"]["spec"]["initContainers"][-1]
    name = "kc4-pg-" + uuid.uuid4().hex[:8]
    r = subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_USER=backstage",
                        "-e", "POSTGRES_PASSWORD=not-a-real-password", "-e", "POSTGRES_DB=backstage",
                        init["image"]], capture_output=True, text=True)
    if r.returncode:
        pytest.skip("cannot start postgres: " + r.stderr[-200:])
    try:
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-q", "-U", "backstage", "-h", "127.0.0.1"]
                              ).returncode == 0:
                break
            time.sleep(1)
        yield name, init["command"]
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _psql(name, db, sql):
    r = subprocess.run(["docker", "exec", "-e", "PGPASSWORD=not-a-real-password", name, "psql", "-h", "127.0.0.1",
                        "-U", "backstage", "-d", db, "-v", "ON_ERROR_STOP=1", "-Atc", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _dedupe(name, command):
    env = ["-e", "PGHOST=127.0.0.1", "-e", "PGPORT=5432", "-e", "PGUSER=backstage",
           "-e", "PGDATABASE=backstage", "-e", "PGPASSWORD=not-a-real-password"]
    r = subprocess.run(["docker", "exec", *env, name, *command], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_init_container_sql_dedupes_and_is_idempotent(postgres):
    name, command = postgres
    for db in ("backstage_plugin_proxy", "backstage_plugin_catalog"):
        _psql(name, "backstage", f"CREATE DATABASE {db}")
    lock = "backstage_backend_public_keys__knex_migrations_lock"
    for db, rows in (("backstage_plugin_proxy", 2), ("backstage_plugin_catalog", 1)):
        _psql(name, db, f"CREATE TABLE {lock} (index serial primary key, is_locked integer)")
        _psql(name, db, f"CREATE TABLE knex_migrations_lock (index serial primary key, is_locked integer)")
        for _ in range(rows):
            _psql(name, db, f"INSERT INTO {lock} (is_locked) VALUES (0)")
        _psql(name, db, "INSERT INTO knex_migrations_lock (is_locked) VALUES (0)")
    # an unrelated table that merely has two rows is left alone
    _psql(name, "backstage_plugin_proxy", "CREATE TABLE other (x int); INSERT INTO other VALUES (1),(2)")
    first = _psql(name, "backstage_plugin_proxy", f"SELECT min(ctid)::text FROM {lock}")

    out = _dedupe(name, command)
    assert "backstage_plugin_proxy" in out and "had 2 rows, kept 1" in out and "1 table(s) repaired" in out, out
    assert _psql(name, "backstage_plugin_proxy", f"SELECT count(*) FROM {lock}") == "1"
    assert _psql(name, "backstage_plugin_proxy", f"SELECT ctid::text FROM {lock}") == first
    assert _psql(name, "backstage_plugin_catalog", f"SELECT count(*) FROM {lock}") == "1"
    assert _psql(name, "backstage_plugin_proxy", "SELECT count(*) FROM other") == "2"

    again = _dedupe(name, command)
    assert "0 table(s) repaired" in again, again


def test_init_container_sql_on_a_fresh_database(postgres):
    name, command = postgres
    _psql(name, "backstage", "CREATE DATABASE fresh_check")  # not a backstage db: ignored
    out = _dedupe(name, command)
    assert "table(s) repaired" in out, out


# ── the same task under go-task's own shell (mvdan/sh), not bash ───────────────

def _run_go_task(tmp_path, state, **extra):
    """Run hub:restart-backstage's cmds with the real `task` binary: go-task's shell lacks
    some builtins (umask) and kills plain background jobs, which bash -c would not show."""
    if not shutil.which("task"):
        pytest.skip("go-task not on PATH")
    env, sim = _env(tmp_path, state)
    env.update(INSTALL_TIMING_LOG=str(tmp_path / "timing.log"),
               BACKSTAGE_GATE_LOG=str(tmp_path / "gate.log"), **extra)
    task = yaml.safe_load(open(TASKFILE))["tasks"]["hub:restart-backstage"]
    tf = {"version": "3",
          "vars": {"HUB_CLUSTER_NAME": "acme-hub", "C_STEP": "", "C_OK": "", "C_RESET": "",
                   "C_INFO": "", "C_WARN": "", "C_ERR": ""},
          "tasks": {"go": {"vars": task["vars"], "cmds": [c for c in task["cmds"] if isinstance(c, str)]}}}
    d = tmp_path / "tf"
    d.mkdir()
    (d / "Taskfile.yaml").write_text(yaml.safe_dump(tf, allow_unicode=True).replace("{{.ROOT_DIR}}", REPO))
    r = subprocess.run(["task", "-d", str(d), "go"], env=env, capture_output=True, text=True, timeout=60)
    return r, json.loads(sim.read_text())


def test_go_task_background_gate(tmp_path, hub_kubeconfig):
    t0 = time.time()
    r, _ = _run_go_task(tmp_path, _state(deploy=False, pods=[], deploy_after=3))
    assert r.returncode == 0, r.stdout + r.stderr
    assert time.time() - t0 < 20  # the install is not held by the gate
    assert "NOT verified yet" in r.stdout and "Backstage healthy" not in r.stdout
    gate_log = _wait_for(tmp_path / "gate.log", "backstage-gate (bg) done")
    assert "gate passed" in gate_log and "rc=0" in gate_log, gate_log


def test_go_task_not_installed_and_present(tmp_path):
    r, _ = _run_go_task(tmp_path, _state(deploy=False, pods=[], backstage_app=False, hub_labels={}))
    assert r.returncode == 0 and "Backstage not installed: skipped" in r.stdout and "healthy" not in r.stdout
    d = tmp_path / "present"; d.mkdir()
    r, _ = _run_go_task(d, _state(pods=[{"name": "backstage-0", "start": AFTER, "deleting": False,
                                         "phase": "initialized", "polls_to_init": 0}]))
    assert r.returncode == 0 and "Backstage healthy" in r.stdout, r.stdout + r.stderr
    d = tmp_path / "broken"; d.mkdir()
    r, _ = _run_go_task(d, _state(always_fail=True))
    assert r.returncode != 0 and "Backstage healthy" not in r.stdout
