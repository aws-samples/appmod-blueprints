"""Hermetic tests for the CICDPipeline DORA setup (cicd-pipeline.yaml, the dora-setup
WorkflowTemplate):

- its step `devlake-init` converges on a re-run, whether the earlier run stopped after creating
  the DevLake project and webhook (node lost, workflow recreated, a retry of the step) or
  completed;
- the whole setup seeds the demo history once per webhook connection (#1092): a re-run with the
  same connection does not seed it again, a replaced connection and a failed seed do.

Each step's script is read verbatim from the RGD, its Argo parameters are filled in, and it runs
with the container's shell. `curl` is a fake DevLake that keeps its projects, blueprints, webhook
connections and the webhook records pushed to them in a JSON file and answers like DevLake
v1.0.3-beta7 (a second project or webhook with the same name is rejected; a webhook's API key
is returned only when it is created; a blueprint PATCH applies the body's `name` and rejects an
empty one; a connection GET returns its `createdAt`; a webhook push needs the connection's key).
`kubectl` is a fake namespace that allows only what the RGD's Role allows on Secrets and
ConfigMaps. The workflow harness runs the `dora-provisioner` DAG's tasks in order, as Argo does:
inputs from earlier tasks' results and output parameters, env from the fake namespace, and a
failed task stops the run. `apk`, `apt` and `sleep` are no-ops. No cluster, no network.

Run:  python -m pytest workshop/scripts/tests/test_dora_setup_rerun.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
for _tool in ("sh", "bash", "jq", "openssl"):
    if not shutil.which(_tool):
        pytest.skip(f"{_tool} not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests",
                   "cicd-pipeline", "cicd-pipeline.yaml")
BASE = "http://devlake.test:8080"

FAKE_CURL = r'''#!PYTHON
import itertools, json, os, re, sys
args, method, data, url, outfile, wfmt = sys.argv[1:], None, None, None, None, None
headers = []
i = 0
while i < len(args):
    a = args[i]
    if a in ("-X", "-H", "-d", "-o", "-w"):
        if a == "-X": method = args[i + 1]
        if a == "-H": headers.append(args[i + 1])
        if a == "-d": data = args[i + 1]
        if a == "-o": outfile = args[i + 1]
        if a == "-w": wfmt = args[i + 1]
        i += 2; continue
    if a.startswith("http"): url = a
    i += 1
method = method or ("POST" if data else "GET")
if os.environ.get("FAKE_DEVLAKE_DOWN") == "1":
    sys.stdout.write((wfmt or "").replace("%{http_code}", "000"))
    sys.exit(7)  # connection refused
path = re.sub(r"^https?://[^/]+", "", url)
f = os.environ["FAKE_DEVLAKE_STATE"]
st = json.load(open(f))
st["calls"].append(f"{method} {path}")
err = lambda msg: {"success": False, "message": msg}
out, code = {"success": True, "message": "success"}, 200
m = lambda p: re.fullmatch(p, path)
if m(r"/proceed-db-migration"):
    pass
elif m(r"/projects/([^/]+)") and method == "GET":
    name = m(r"/projects/([^/]+)").group(1)
    p = st["projects"].get(name)
    out = {"name": name, "blueprint": st["blueprints"][str(p)]} if p else err("could not find project")
elif m(r"/projects") and method == "POST":
    name = json.loads(data)["name"]
    if name in st["projects"]:
        out = err(f"A project with name [{name}] already exists")
    else:
        bp = st["next_id"]; st["next_id"] += 1
        st["blueprints"][str(bp)] = {"id": bp, "name": f"{name}-Blueprint", "connections": []}
        st["projects"][name] = bp
        out = {"name": name, "blueprint": st["blueprints"][str(bp)]}
elif m(r"/plugins/webhook/connections/by-name/([^/]+)") and method == "GET":
    name = m(r"/plugins/webhook/connections/by-name/([^/]+)").group(1)
    c = [v for v in st["connections"].values() if v["name"] == name]
    out = {"id": c[0]["id"], "name": name} if c else err("record not found")
elif m(r"/plugins/webhook/connections") and method == "POST":
    name = json.loads(data)["name"]
    if any(v["name"] == name for v in st["connections"].values()):
        out = err(f"A webhook with name {name} already exists.")
    else:
        cid = st["next_id"]; st["next_id"] += 1
        created = "2026-10-%02dT06:19:%02d.178Z" % (st.get("db", 1), cid)  # a new database: another day
        st["connections"][str(cid)] = {"id": cid, "name": name, "key": f"key-{cid}", "createdAt": created}
        out = {"id": cid, "name": name, "createdAt": created, "apiKey": {"apiKey": f"key-{cid}"}}
elif m(r"/plugins/webhook/connections/(\d+)") and method == "GET":
    c = st["connections"].get(m(r"/plugins/webhook/connections/(\d+)").group(1))
    if c:  # no key: DevLake returns it only on create
        out = {"id": c["id"], "name": c["name"], "createdAt": c["createdAt"], "updatedAt": c["createdAt"]}
    else:
        out, code = err("record not found (404)"), 404
elif m(r"/api/rest/plugins/webhook/connections/(\d+)/(pull_requests|deployments|issues)") and method == "POST":
    cid, kind = m(r"/api/rest/plugins/webhook/connections/(\d+)/(pull_requests|deployments|issues)").groups()
    c = st["connections"].get(cid)
    rows = st.setdefault("rows", {}).setdefault(cid, {"pull_requests": 0, "deployments": 0, "issues": 0})
    fail_at = os.environ.get("FAKE_DEVLAKE_FAIL_AT_DEPLOYMENT")
    if not c or f"Authorization: Bearer {c['key']}" not in headers:
        out, code = err("invalid api key"), 403
    elif kind == "deployments" and fail_at and rows["deployments"] >= int(fail_at):
        out, code = err("DevLake is down"), 503  # past curl's retries
    else:
        json.loads(data)
        rows[kind] += 1
elif m(r"/blueprints/(\d+)/trigger") and method == "POST":
    st.setdefault("triggers", []).append(int(m(r"/blueprints/(\d+)/trigger").group(1)))
elif m(r"/plugins/webhook/connections/(\d+)") and method == "DELETE":
    if os.environ.get("FAKE_DEVLAKE_DELETE_FAILS") == "1":
        out, code = err("internal error"), 500
    else:
        st["connections"].pop(m(r"/plugins/webhook/connections/(\d+)").group(1), None)
elif m(r"/blueprints/(\d+)") and method == "PATCH":
    bp = st["blueprints"].get(m(r"/blueprints/(\d+)").group(1))
    body = json.loads(data)
    if not bp:
        out = err("blueprint not found")
    elif not body.get("name"):
        out = err("Key: 'Blueprint.Name' Error:Field validation for 'Name' failed on the 'required' tag")
    else:
        bp["name"] = body["name"]
        bp["connections"] = [c["connectionId"] for c in body["connections"]]
        out = dict(bp)
else:
    out = err(f"unexpected {method} {path}")
if out.get("success") is False and code == 200:
    code = 400
json.dump(st, open(f, "w"))
if "--fail" in args and code >= 400:
    sys.stderr.write(f"curl: (22) The requested URL returned error: {code}\n")
    sys.exit(22)
if outfile != "/dev/null":
    print(json.dumps(out))
sys.stdout.write((wfmt or "").replace("%{http_code}", str(code)))
'''


def _step():
    rgd = yaml.safe_load(open(RGD))
    (wft,) = [r["template"] for r in rgd["spec"]["resources"] if r["id"] == "dorasetuptemplate"]
    templates = {t["name"]: t for t in wft["spec"]["templates"]}
    return templates["devlake-init"]["container"], templates["create-devlake-webhook-secret-and-cm"]


def _existing_env(token, hook_id):
    """The env the step gets from what an earlier run's next step wrote into the namespace."""
    container, writer = _step()
    written = {"devlake-webhook-secret": {"DEVLAKE_TOKEN": token},
               "devlake-webhook-id": {"DEVLAKE_HOOK_ID": hook_id}}
    env = {}
    for e in container.get("env", []):
        ref = e["valueFrom"].get("secretKeyRef") or e["valueFrom"].get("configMapKeyRef")
        assert ref["optional"] is True and ref["name"] in writer["container"]["args"][0]
        env[e["name"]] = written[ref["name"]][ref["key"]]
    return env


@pytest.fixture
def devlake(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "curl").write_text(FAKE_CURL.replace("#!PYTHON", "#!" + sys.executable))
    (bindir / "apk").write_text("#!/bin/sh\nexit 0\n")
    for tool in ("curl", "apk"):
        (bindir / tool).chmod(0o755)
    state = tmp_path / "devlake.json"
    state.write_text(json.dumps({"projects": {}, "blueprints": {}, "connections": {},
                                 "next_id": 1, "calls": []}))
    script = _step()[0]["args"][0]
    script = script.replace("{{inputs.parameters.url}}", BASE)
    script = script.replace("{{inputs.parameters.appname}}", "java")
    assert "{{" not in script
    (tmp_path / "devlake-init.sh").write_text(script)

    class DevLake:
        def run(self, down=False, **env):
            res = subprocess.run(
                ["sh", str(tmp_path / "devlake-init.sh")], capture_output=True, text=True,
                timeout=60, env=dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                                     FAKE_DEVLAKE_STATE=str(state),
                                     FAKE_DEVLAKE_DOWN="1" if down else "0", **env))
            # all of stdout: it is the step's result, which the next step splits on '|'
            return res.returncode, res.stdout.strip().splitlines() or [""], res.stderr

        def state(self):
            return json.loads(state.read_text())

        def seed(self, project=False, connection=False, attached=False):
            st = self.state()
            if project:
                st["blueprints"]["1"] = {"id": 1, "name": "java-Blueprint",
                                         "connections": [2] if attached else []}
                st["projects"]["java"] = 1
            if connection:
                st["connections"]["2"] = {"id": 2, "name": "java_webhook", "key": "key-2"}
            st["next_id"] = 3
            state.write_text(json.dumps(st))

    return DevLake()


def test_rerun_after_an_interrupted_setup_converges(devlake):
    # The first run created the project and the webhook, then its node died before the
    # Secret was written: nothing in the namespace holds the webhook's key.
    devlake.seed(project=True, connection=True, attached=True)
    rc, (out,), err = devlake.run()
    assert rc == 0, err
    key, hook, bp = out.split("|")
    st = devlake.state()
    assert bp == "1" and list(st["projects"]) == ["java"]           # project reused
    assert list(st["connections"]) == [hook] and hook != "2"        # webhook replaced ...
    assert key == st["connections"][hook]["key"]                    # ... with a key we know
    assert st["blueprints"]["1"]["connections"] == [int(hook)]      # and attached
    assert st["blueprints"]["1"]["name"] == "java-Blueprint"        # PATCH kept its name
    assert "Replacing webhook connection 2: DELETE HTTP 200" in err


def test_retry_after_a_partial_create_converges(devlake):
    # DevLake is down: the step fails, so Argo retries it (#1029), and nothing is created
    rc, _, err = devlake.run(down=True)
    assert rc != 0 and "DevLake setup failed" in err
    # an attempt created the project, then DevLake restarted before the webhook POST
    devlake.seed(project=True)
    rc, (out,), err = devlake.run()
    assert rc == 0, err
    key, hook, bp = out.split("|")
    st = devlake.state()
    assert bp == "1" and list(st["projects"]) == ["java"]
    assert st["connections"][hook]["key"] == key
    assert st["blueprints"]["1"]["connections"] == [int(hook)]
    assert st["blueprints"]["1"]["name"] == "java-Blueprint"


def test_rerun_after_a_completed_setup_keeps_the_webhook(devlake):
    rc, (first,), err = devlake.run()                               # fresh install
    assert rc == 0, err
    key, hook, bp = first.split("|")
    calls = len(devlake.state()["calls"])
    # e.g. the workflow is deleted and kro recreates it: the Secret and ConfigMap are there
    rc, (again,), err = devlake.run(**_existing_env(key, hook))
    assert rc == 0, err
    assert again == first                                           # same key, id, blueprint
    st = devlake.state()
    new_calls = st["calls"][calls:]
    assert not [c for c in new_calls if c.startswith(("POST", "DELETE"))], new_calls
    assert list(st["connections"]) == [hook] and st["blueprints"][bp]["connections"] == [int(hook)]
    assert st["blueprints"][bp]["name"] == "java-Blueprint"


def test_a_failed_webhook_delete_fails_the_step_with_its_status(devlake):
    # An interrupted setup left the webhook, and DevLake does not delete it: say so, rather
    # than POSTing a duplicate and failing on the generic "webhook connection id 'null'".
    devlake.seed(project=True, connection=True, attached=True)
    rc, _, err = devlake.run(FAKE_DEVLAKE_DELETE_FAILS="1")
    assert rc != 0
    assert "could not delete webhook connection 2 (HTTP 500)" in err, err
    calls = devlake.state()["calls"]
    assert "POST /plugins/webhook/connections" not in calls, calls
    # the retry converges once DevLake deletes it
    rc, (out,), err = devlake.run()
    assert rc == 0, err
    key, hook, bp = out.split("|")
    st = devlake.state()
    assert list(st["connections"]) == [hook] and st["blueprints"]["1"]["connections"] == [int(hook)]


# --- the whole setup: seed the demo history once per webhook connection (#1092) ---------------

FAKE_KUBECTL = r"""#!PYTHON
import json, os, sys
args = sys.argv[1:]
f = os.environ["FAKE_NAMESPACE_STATE"]
st = json.load(open(f))
rules = json.loads(os.environ["FAKE_NAMESPACE_RULES"])
verb, kind = args[0], args[1]
name = args[3] if verb == "create" and kind == "secret" else args[2]
kind = {"secret": "secrets", "configmap": "configmaps"}[kind]
lit = dict(a[len("--from-literal="):].split("=", 1) for a in args if a.startswith("--from-literal="))
assert args[args.index("-n") + 1] == st["namespace"], args
if not any("" in r["apiGroups"] and kind in r["resources"] and verb in r["verbs"]
           and name in r.get("resourceNames", [name]) for r in rules):
    sys.exit(f"Error from server (Forbidden): cannot {verb} {kind} {name}")
objs = st[kind]
if verb == "delete":
    if name not in objs and "--ignore-not-found" not in args:
        sys.exit(f"Error from server (NotFound): {kind} {name} not found")
    objs.pop(name, None)
elif verb == "create":
    if name in objs:
        sys.exit(f"Error from server (AlreadyExists): {kind} {name} already exists")
    objs[name] = lit
else:
    sys.exit(f"fake kubectl: unsupported {args}")
json.dump(st, open(f, "w"))
"""


def _rgd():
    rgd = yaml.safe_load(open(RGD))
    (wft,) = [r["template"] for r in rgd["spec"]["resources"] if r["id"] == "dorasetuptemplate"]
    (role,) = [r["template"] for r in rgd["spec"]["resources"] if r["id"] == "role"]
    return wft, role["rules"]


@pytest.fixture
def workflow(tmp_path):
    """Runs the dora-provisioner DAG for app java in namespace team-java, as Argo would."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    py = "#!" + sys.executable
    (bindir / "curl").write_text(FAKE_CURL.replace("#!PYTHON", py))
    (bindir / "kubectl").write_text(FAKE_KUBECTL.replace("#!PYTHON", py))
    for tool in ("apk", "apt", "sleep"):
        (bindir / tool).write_text("#!/bin/sh\nexit 0\n")
    for tool in ("curl", "kubectl", "apk", "apt", "sleep"):
        (bindir / tool).chmod(0o755)
    devlake, ns = tmp_path / "devlake.json", tmp_path / "namespace.json"
    fresh_db = lambda db: {"projects": {}, "blueprints": {}, "connections": {}, "next_id": 1,
                           "calls": [], "rows": {}, "triggers": [], "db": db}
    devlake.write_text(json.dumps(fresh_db(1)))
    ns.write_text(json.dumps({"namespace": "team-java", "secrets": {}, "configmaps": {}}))
    wft, rules = _rgd()
    params = {p["name"]: p["value"] for p in wft["spec"]["arguments"]["parameters"]}
    params.update(appname="java", namespace="team-java")
    templates = {t["name"]: t for t in wft["spec"]["templates"]}
    tasks = templates["dora-provisioner"]["dag"]["tasks"]

    class Run:
        def __init__(self):
            self.out, self.failed = {}, None

    class Workflow:
        runs = 0

        def devlake(self):
            return json.loads(devlake.read_text())

        def namespace(self):
            return json.loads(ns.read_text())

        def delete(self, kind, name):
            st = self.namespace()
            del st[kind][name]
            ns.write_text(json.dumps(st))

        def new_devlake_database(self):
            """DevLake's database replaced (a new Aurora cluster): ids start at 1 again."""
            devlake.write_text(json.dumps(fresh_db(self.devlake()["db"] + 1)))

        def _env(self, container):
            st, env = self.namespace(), {}
            for e in container.get("envFrom", []):
                ref = e.get("secretRef") or e.get("configMapRef")
                obj = st["secrets" if "secretRef" in e else "configmaps"].get(ref["name"])
                if obj is None and not ref.get("optional"):
                    return None  # CreateContainerConfigError
                env.update(obj or {})
            for e in container.get("env", []):
                ref = e["valueFrom"].get("secretKeyRef") or e["valueFrom"].get("configMapKeyRef")
                kind = "secrets" if "secretKeyRef" in e["valueFrom"] else "configmaps"
                value = st[kind].get(ref["name"], {}).get(ref["key"])
                if value is None and not ref.get("optional"):
                    return None
                if value is not None:
                    env[e["name"]] = value
            return env

        def run(self, **fake_env):
            Workflow.runs += 1
            run, results, outputs = Run(), {}, {}
            for task in tasks:
                assert task.get("depends", "") in ("",) + tuple(results), task  # a linear DAG
                t = templates[task["template"]]
                inputs = {}
                for a in task.get("arguments", {}).get("parameters", []):
                    v = a["value"].replace("{{workflow.parameters.appname}}", params["appname"])
                    for name, res in results.items():
                        v = v.replace("{{tasks.%s.outputs.result}}" % name, res)
                    for (name, p), val in outputs.items():
                        v = v.replace("{{tasks.%s.outputs.parameters.%s}}" % (name, p), val)
                    inputs[a["name"]] = v
                container = t["container"]
                script = container["args"][0]
                for k, v in inputs.items():
                    script = script.replace("{{inputs.parameters.%s}}" % k, v)
                for k, v in params.items():
                    script = script.replace("{{workflow.parameters.%s}}" % k, v)
                paths = {}
                for p in t.get("outputs", {}).get("parameters", []):
                    paths[p["name"]] = str(tmp_path / f"run{Workflow.runs}-{task['name']}-{p['name']}")
                    script = script.replace(p["valueFrom"]["path"], paths[p["name"]])
                assert "{{" not in script, task["name"]
                f = tmp_path / f"run{Workflow.runs}-{task['name']}.sh"
                f.write_text(script)
                env = self._env(container)
                if env is None:
                    run.failed = task["name"]
                    return run
                shell = os.path.basename(container["command"][0])
                res = subprocess.run(
                    [shell, str(f)], capture_output=True, text=True, timeout=300,
                    env=dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                             FAKE_DEVLAKE_STATE=str(devlake), FAKE_NAMESPACE_STATE=str(ns),
                             FAKE_NAMESPACE_RULES=json.dumps(rules), **env, **fake_env))
                run.out[task["name"]] = res
                if res.returncode != 0:
                    run.failed = task["name"]
                    return run
                results[task["name"]] = res.stdout.strip()
                for p, path in paths.items():
                    outputs[(task["name"], p)] = open(path).read().rstrip("\n")
            return run

    return Workflow()


def _seeded(run):
    """The deployments the seed reports it created, from devlake-generate-data's log."""
    line = [l for l in run.out["devlake-generate-data"].stdout.splitlines()
            if l.startswith("Data generation complete.")]
    return int(line[0].split(" deployments")[0].rsplit(" ", 1)[1]) if line else 0


def _pushes(calls):
    return [c for c in calls if c.startswith("POST /api/rest/plugins/webhook/")]


def _marker(workflow):
    return workflow.namespace()["configmaps"].get("devlake-demo-data")


def test_fresh_setup_seeds_once_and_marks_the_connection(workflow):
    run = workflow.run()
    assert run.failed is None, run.out[run.failed].stderr
    st = workflow.devlake()
    (hook,) = st["connections"]
    assert st["rows"][hook]["deployments"] == _seeded(run) > 0
    assert st["triggers"] == [st["projects"]["java"]]
    assert _marker(workflow) == {"SEEDED_HOOK_ID": hook,
                                 "SEEDED_HOOK_CREATED_AT": st["connections"][hook]["createdAt"]}


def test_rerun_with_the_same_connection_does_not_seed_again(workflow):
    assert workflow.run().failed is None
    st = workflow.devlake()
    rows, calls, marker = st["rows"], len(st["calls"]), _marker(workflow)
    # the workflow is deleted and kro recreates it: devlake-init keeps the connection
    run = workflow.run()
    assert run.failed is None, run.out[run.failed].stderr
    st = workflow.devlake()
    assert list(st["connections"]) == list(rows)                    # same connection ...
    assert not _pushes(st["calls"][calls:]), _pushes(st["calls"][calls:])  # ... nothing seeded
    assert st["rows"] == rows
    assert st["triggers"] == [st["projects"]["java"]] * 2           # blueprint still triggered
    assert "not seeding it again" in run.out["devlake-generate-data"].stdout
    assert _marker(workflow) == marker


def test_rerun_after_the_connection_is_replaced_seeds_it_once(workflow):
    assert workflow.run().failed is None
    (old,) = workflow.devlake()["connections"]
    old_rows = workflow.devlake()["rows"][old]
    # the workaround in #1092, or an interrupted setup: no Secret/ConfigMap holds the key
    workflow.delete("secrets", "devlake-webhook-secret")
    workflow.delete("configmaps", "devlake-webhook-id")
    run = workflow.run()
    assert run.failed is None, run.out[run.failed].stderr
    st = workflow.devlake()
    (new,) = st["connections"]
    assert new != old
    assert st["rows"][new]["deployments"] == _seeded(run) > 0      # one history for the new one
    assert st["rows"][old] == old_rows                              # DevLake keeps the old rows
    assert _marker(workflow) == {"SEEDED_HOOK_ID": new,
                                 "SEEDED_HOOK_CREATED_AT": st["connections"][new]["createdAt"]}
    # and the next re-run keeps it and seeds nothing
    calls = len(st["calls"])
    assert workflow.run().failed is None
    assert not _pushes(workflow.devlake()["calls"][calls:])


def test_a_new_devlake_database_is_seeded_even_with_the_same_connection_id(workflow):
    assert workflow.run().failed is None
    (hook,) = workflow.devlake()["connections"]
    created = workflow.devlake()["connections"][hook]["createdAt"]
    workflow.new_devlake_database()
    run = workflow.run()
    assert run.failed is None, run.out[run.failed].stderr
    st = workflow.devlake()
    assert list(st["connections"]) == [hook]                        # the same id again ...
    assert st["connections"][hook]["createdAt"] != created          # ... for a new connection
    assert st["rows"][hook]["deployments"] == _seeded(run) > 0
    assert _marker(workflow)["SEEDED_HOOK_CREATED_AT"] == st["connections"][hook]["createdAt"]


def test_a_seed_that_fails_midway_writes_no_marker_and_the_next_run_seeds(workflow):
    # DevLake goes away (past curl's retries) after 10 deployments: the step fails
    run = workflow.run(FAKE_DEVLAKE_FAIL_AT_DEPLOYMENT="10")
    assert run.failed == "devlake-generate-data"
    assert _marker(workflow) is None
    (hook,) = workflow.devlake()["connections"]
    assert workflow.devlake()["rows"][hook]["deployments"] == 10
    assert workflow.devlake()["triggers"] == []
    # the re-run keeps the connection (the Secret was written) and seeds the full history
    run = workflow.run()
    assert run.failed is None, run.out[run.failed].stderr
    st = workflow.devlake()
    assert list(st["connections"]) == [hook]
    assert st["rows"][hook]["deployments"] == 10 + _seeded(run) and _seeded(run) > 10
    assert _marker(workflow) == {"SEEDED_HOOK_ID": hook,
                                 "SEEDED_HOOK_CREATED_AT": st["connections"][hook]["createdAt"]}
