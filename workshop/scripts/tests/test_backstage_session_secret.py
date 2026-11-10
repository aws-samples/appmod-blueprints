"""Hermetic test: Backstage auth.session.secret must come from a Secret, never the ConfigMap.

Renders the backstage chart with `helm template` and asserts: no literal session secret in
the app-config, the container loads backstage-session-vars via envFrom, the ExternalSecret
produces that Secret from <hub>/secrets and tolerates a missing backstage_session_secret
key (upgrade path), and both cluster providers seed the key idempotently.

Run:  python -m pytest workshop/scripts/tests/test_backstage_session_secret.py -q
"""
import os
import re
import shutil
import subprocess

import pytest
import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "backstage")
OLD_LITERAL = "MW2sV-sIPngEl26vAzatV-6VqfsgAx4bPIz7PuE_2Lk="
TASKFILES = [
    os.path.join(REPO, "cluster-providers", d, "Taskfile.yaml") for d in ("kind-crossplane", "kind-kro-ack")
]

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module")
def rendered():
    out = subprocess.run(
        ["helm", "template", "x", CHART, "--set", "global.aws_cluster_name=peeks-hub"],
        check=True, capture_output=True, text=True,
    ).stdout
    return out, [d for d in yaml.safe_load_all(out) if d]


def _find(docs, kind, name):
    return next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name)


def test_old_literal_gone_and_config_uses_env_reference(rendered):
    text, docs = rendered
    assert OLD_LITERAL not in text
    cfg = _find(docs, "ConfigMap", "backstage-config")
    app_config = next(v for v in cfg["data"].values() if "auth:" in v)
    assert yaml.safe_load(app_config)["auth"]["session"]["secret"] == "${BACKSTAGE_SESSION_SECRET}"


def test_container_loads_session_secret_via_envfrom(rendered):
    _, docs = rendered
    dep = _find(docs, "Deployment", "backstage")
    envfrom = [c for ct in dep["spec"]["template"]["spec"]["containers"] for c in ct.get("envFrom", [])]
    refs = [e["secretRef"] for e in envfrom if "secretRef" in e]
    entry = [r for r in refs if r["name"] == "backstage-session-vars"]
    assert entry and not entry[0].get("optional")


def test_external_secret_feeds_session_vars_and_tolerates_missing_key(rendered):
    _, docs = rendered
    es = _find(docs, "ExternalSecret", "backstage-session")
    spec = es["spec"]
    assert spec["target"]["name"] == "backstage-session-vars"
    assert spec["dataFrom"][0]["extract"]["key"] == "peeks-hub/secrets"
    assert "data" not in spec  # a per-property remoteRef would fail when the key is absent


GO_HARNESS = """package main
import ("encoding/json";"fmt";"os";"text/template";"github.com/Masterminds/sprig/v3")
func main(){
 var d map[string]string
 json.Unmarshal([]byte(os.Args[2]),&d)
 t,err:=template.New("x").Option("missingkey=error").Funcs(sprig.TxtFuncMap()).Parse(os.Args[1])
 if err!=nil{fmt.Print("ERR:",err);return}
 var b bytesBuf
 if err:=t.Execute(&b,d);err!=nil{fmt.Print("ERR:",err);return}
 fmt.Print(b.s)
}
type bytesBuf struct{s string}
func (b *bytesBuf) Write(p []byte)(int,error){b.s+=string(p);return len(p),nil}
"""
GO_MOD = """module t
go 1.21
require github.com/Masterminds/sprig/v3 v3.3.0
"""


@pytest.fixture(scope="module")
def eso_render(rendered, tmp_path_factory):
    """Execute the ExternalSecret template exactly as ESO does (Go text/template, sprig,
    missingkey=error, map[string]string). Skipped when go or the sprig module is unavailable."""
    if shutil.which("go") is None:
        pytest.skip("go not installed")
    d = tmp_path_factory.mktemp("eso")
    (d / "main.go").write_text(GO_HARNESS)
    (d / "go.mod").write_text(GO_MOD)
    env = dict(os.environ, GOFLAGS="-mod=mod", GONOSUMDB="*", GOPROXY="off")
    b = subprocess.run(["go", "build", "-o", "h", "."], cwd=d, env=env, capture_output=True, text=True)
    if b.returncode:
        pytest.skip("harness build failed: " + b.stderr[-200:])
    _, docs = rendered
    expr = _find(docs, "ExternalSecret", "backstage-session")["spec"]["target"]["template"]["data"][
        "BACKSTAGE_SESSION_SECRET"]
    return lambda data, e=None: subprocess.run(
        [str(d / "h"), e or expr, __import__("json").dumps(data)], check=True, capture_output=True, text=True).stdout


def test_eso_template_uses_index_form(rendered):
    _, docs = rendered
    expr = _find(docs, "ExternalSecret", "backstage-session")["spec"]["target"]["template"]["data"][
        "BACKSTAGE_SESSION_SECRET"]
    assert 'index . "backstage_session_secret"' in expr
    assert ".backstage_session_secret" not in expr  # field access errors under missingkey=error


def test_eso_template_execution(eso_render):
    import hashlib
    pg = "pw"
    sha = hashlib.sha256(pg.encode()).hexdigest()
    out = eso_render({"backstage_postgres_password": pg})
    assert re.fullmatch(r"[0-9a-f]{64}", out) and out == sha
    assert eso_render({"backstage_postgres_password": pg, "backstage_session_secret": "S"}) == "S"
    assert eso_render({"backstage_postgres_password": pg, "backstage_session_secret": ""}) == sha


def test_eso_template_old_expression_fails_on_missing_key(eso_render):
    old = "{{ .backstage_session_secret | toString | default (.backstage_postgres_password | toString | sha256sum) }}"
    assert eso_render({"backstage_postgres_password": "pw"}, old).startswith("ERR:")


@pytest.mark.parametrize("taskfile", TASKFILES)
def test_seed_adds_missing_key_and_keeps_existing(taskfile):
    t = open(taskfile).read()
    m = re.search(
        r"(if ! echo \"\$UPDATED\" \| jq -e 'has\(\"backstage_session_secret\"\)'.*?\n\s+fi\n)", t, re.S)
    assert m, "backstage_session_secret seed block missing"
    block = m.group(1)
    assert "see docs" not in t[m.start() - 400:m.end()]

    def run(updated):
        return subprocess.run(
            ["bash", "-c", "UPDATED=\"$1\"\n" + block + "echo \"$UPDATED\"", "_", updated],
            check=True, capture_output=True, text=True,
        ).stdout

    import json
    added = json.loads(run('{"a":"1"}'))
    assert added["a"] == "1" and len(added["backstage_session_secret"]) >= 32
    kept = json.loads(run('{"backstage_session_secret":"keep-me"}'))
    assert kept["backstage_session_secret"] == "keep-me"
