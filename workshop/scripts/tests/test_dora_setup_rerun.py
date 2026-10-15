"""Hermetic tests for the CICDPipeline DORA setup step `devlake-init` (cicd-pipeline.yaml): a
re-run converges, whether the earlier run stopped after creating the DevLake project and
webhook (node lost, workflow recreated, a retry of the step) or completed.

The step's script is read verbatim from the RGD's dora-setup WorkflowTemplate, its Argo
parameters are filled in, and it runs with sh. `curl` is a fake DevLake that keeps its
projects, blueprints and webhook connections in a JSON file and answers like DevLake
v1.0.3-beta7 (a second project or webhook with the same name is rejected; a webhook's API key
is returned only when it is created). `apk` is a no-op. No cluster, no network.

Run:  python -m pytest workshop/scripts/tests/test_dora_setup_rerun.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")
for _tool in ("sh", "jq"):
    if not shutil.which(_tool):
        pytest.skip(f"{_tool} not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests",
                   "cicd-pipeline", "cicd-pipeline.yaml")
BASE = "http://devlake.test:8080"

FAKE_CURL = r'''#!PYTHON
import itertools, json, os, re, sys
args, method, data, url = sys.argv[1:], None, None, None
i = 0
while i < len(args):
    a = args[i]
    if a in ("-X", "-H", "-d"):
        if a == "-X": method = args[i + 1]
        if a == "-d": data = args[i + 1]
        i += 2; continue
    if a.startswith("http"): url = a
    i += 1
method = method or ("POST" if data else "GET")
if os.environ.get("FAKE_DEVLAKE_DOWN") == "1":
    sys.exit(7)  # connection refused
path = re.sub(r"^https?://[^/]+", "", url)
f = os.environ["FAKE_DEVLAKE_STATE"]
st = json.load(open(f))
st["calls"].append(f"{method} {path}")
err = lambda msg: {"success": False, "message": msg}
out = {"success": True, "message": "success"}
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
        st["connections"][str(cid)] = {"id": cid, "name": name, "key": f"key-{cid}"}
        out = {"id": cid, "name": name, "apiKey": {"apiKey": f"key-{cid}"}}
elif m(r"/plugins/webhook/connections/(\d+)") and method == "DELETE":
    st["connections"].pop(m(r"/plugins/webhook/connections/(\d+)").group(1), None)
elif m(r"/blueprints/(\d+)") and method == "PATCH":
    bp = st["blueprints"].get(m(r"/blueprints/(\d+)").group(1))
    if bp:
        bp["connections"] = [c["connectionId"] for c in json.loads(data)["connections"]]
        out = dict(bp)
    else:
        out = err("blueprint not found")
else:
    out = err(f"unexpected {method} {path}")
json.dump(st, open(f, "w"))
print(json.dumps(out))
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
            return res.returncode, res.stdout.strip().splitlines()[-1:] or [""], res.stderr

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


def test_retry_after_a_partial_create_converges(devlake):
    # DevLake is down: the step fails, so Argo retries it (#1026), and nothing is created
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
