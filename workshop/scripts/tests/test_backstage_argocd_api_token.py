"""Hermetic tests: the Backstage Argo CD plugin can authenticate with an API token.

The EKS managed Argo CD capability has no local login, so the plugin's username/password
pair never gets a session and the entity Argo CD card finds no app. The chart now passes an
optional API token (ExternalSecret argocd-api-token, property argocd_api_token of
<cluster>/secrets) that the plugin prefers when it is non-empty.

Checks: the instance has `token: ${ARGOCD_AUTH_TOKEN}` and keeps username/password as the
fallback; the ExternalSecret reads the property with `index` (a missing property renders ""
instead of failing the sync, ESO runs templates with missingkey=error); the Deployment reads
the secret with optional: true; the mint script parses.

Run:  python -m pytest workshop/scripts/tests/test_backstage_argocd_api_token.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "backstage")
SCRIPT = os.path.join(REPO, "scripts", "backstage-argocd-token.sh")


@pytest.fixture(scope="module")
def rendered():
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    out = subprocess.run(
        ["helm", "template", "b", CHART,
         "--set", "global.aws_cluster_name=test-hub",
         "--set", "argocd_hostname=argocd.example.com"],
        capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _one(rendered, kind, name):
    found = [d for d in rendered if d["kind"] == kind and d["metadata"]["name"] == name]
    assert len(found) == 1, (kind, name, len(found))
    return found[0]


def test_instance_prefers_token_and_keeps_password_fallback(rendered):
    cfg = _one(rendered, "ConfigMap", "backstage-config")
    app = yaml.safe_load(cfg["data"]["app-config.yaml"])
    inst = app["argocd"]["appLocatorMethods"][0]["instances"][0]
    assert inst["url"] == "https://argocd.example.com"
    assert inst["token"] == "${ARGOCD_AUTH_TOKEN}"
    assert inst["username"] == "admin"
    assert inst["password"] == "${ARGOCD_ADMIN_PASSWORD}"


def test_external_secret_tolerates_a_missing_property(rendered):
    es = _one(rendered, "ExternalSecret", "argocd-api-token")
    spec = es["spec"]
    assert spec["target"]["name"] == "argocd-api-token"
    tpl = spec["target"]["template"]["data"]["ARGOCD_AUTH_TOKEN"]
    assert tpl.replace(" ", "") == '{{index."argocd_api_token"}}', tpl
    assert spec["dataFrom"][0]["extract"]["key"] == "test-hub/secrets"
    assert "data" not in spec


def test_deployment_reads_the_token_secret_optionally(rendered):
    dep = _one(rendered, "Deployment", "backstage")
    env_from = dep["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    refs = {e["secretRef"]["name"]: e["secretRef"].get("optional", False)
            for e in env_from if "secretRef" in e}
    assert refs.get("argocd-api-token") is True
    # The existing required secrets are unchanged.
    assert refs.get("argocd-credentials") is False


def test_mint_script_parses():
    subprocess.run(["bash", "-n", SCRIPT], check=True)
    assert os.access(SCRIPT, os.X_OK)
