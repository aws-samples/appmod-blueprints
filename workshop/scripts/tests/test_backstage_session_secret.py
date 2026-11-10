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
    expr = spec["target"]["template"]["data"]["BACKSTAGE_SESSION_SECRET"]
    assert "backstage_session_secret" in expr
    # missing key -> derived fallback, not an empty value and not a failed sync
    assert "default" in expr and "sha256sum" in expr
    # a per-property remoteRef would make ESO fail when the key is absent
    assert "data" not in spec


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
