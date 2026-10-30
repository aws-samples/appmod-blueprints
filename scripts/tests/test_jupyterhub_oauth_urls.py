"""JupyterHub's GenericOAuthenticator must get its Keycloak endpoints from the registry.

Without authorize_url the hub redirects /hub/oauth_login to an empty URL and loops on
itself, never reaching Keycloak. The endpoints and the callback are built from the
cluster-secret ``ingress_domain_name`` annotation (same source as argocd and kargo), and
the callback is pinned to https so the CloudFront (insecure, HTTP-to-ALB) mode does not
derive an http:// callback that Keycloak rejects.
"""

import os
import shutil
import subprocess

import pytest
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry")
DOMAIN = "https://{{.metadata.annotations.ingress_domain_name}}"
REALM = DOMAIN + "/keycloak/realms/platform/protocol/openid-connect"
EXPECTED = {
    "oauth_callback_url": DOMAIN + "/jupyterhub/hub/oauth_callback",
    "authorize_url": REALM + "/auth",
    "token_url": REALM + "/token",
    "userdata_url": REALM + "/userinfo",
}


def _registry_oauth():
    with open(os.path.join(REGISTRY, "ml.yaml")) as f:
        entry = yaml.safe_load(f)["jupyterhub"]
    return entry["valuesObject"]["jupyterhub"]["hub"]["config"]["GenericOAuthenticator"]


def test_registry_sets_keycloak_endpoints_from_ingress_domain():
    assert _registry_oauth() == EXPECTED


def test_keycloak_client_redirect_uri_matches_callback():
    path = os.path.join(REPO, "gitops", "addons", "charts", "keycloak", "templates", "keycloak-config.yaml")
    with open(path) as f:
        text = f.read()
    # keycloak-config exports DOMAIN_NAME from the same ingress_domain_name value.
    assert '"https://${DOMAIN_NAME}/jupyterhub/hub/oauth_callback"' in text
    assert "export DOMAIN_NAME={{ .Values.global.ingress_domain_name }}" in text


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_rendered_applicationset_carries_endpoints():
    files = [os.path.join(REGISTRY, "_defaults.yaml")] + sorted(
        os.path.join(REGISTRY, f) for f in os.listdir(REGISTRY) if f.endswith(".yaml")
    )
    args = ["helm", "template", "appsets", os.path.join(REPO, "platform-charts", "appset-chart")]
    for f in files:
        args += ["-f", f]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    appsets = [d for d in yaml.safe_load_all(out) if d and d.get("kind") == "ApplicationSet"
               and "jupyterhub" in d["metadata"]["name"]]
    assert len(appsets) == 1
    sources = appsets[0]["spec"]["template"]["spec"]["sources"]
    chart = [s for s in sources if s.get("path", "").endswith("charts/jupyterhub")][0]
    got = chart["helm"]["valuesObject"]["jupyterhub"]["hub"]["config"]["GenericOAuthenticator"]
    assert got == EXPECTED
