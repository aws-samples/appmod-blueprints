"""Hermetic test: the keycloak-client-provisioner IAM identity is ACK on kro-ack hubs.

Why: the Keycloak app (sync-wave 6 of the addon ApplicationSet) used to own a Crossplane
iam.aws.upbound.io Role (wave 1) and eks.aws.upbound.io PodIdentityAssociation (wave 2).
Their CRDs only exist once the separate crossplane-base app installed provider-aws-iam /
provider-aws-eks, so the Keycloak first sync sat blocked for ~35 min.
On kro-ack the ACK capability already provides iam/eks.services.k8s.aws CRDs, so the
identity there must be ACK; kind-crossplane / byoc keep the Crossplane objects.

Run:  python -m pytest workshop/scripts/tests/test_keycloak_client_provisioner_identity_ack.py -q
"""
import json
import os
import shutil
import subprocess

import pytest
import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "keycloak")
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry", "security.yaml")
IDENTITY_TPL = os.path.join(CHART, "templates", "client-provisioner-identity.yaml")
CLUSTER = "peeks-hub"
ROLE_NAME = f"{CLUSTER}-KeycloakClientProvisionerRole"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def render(*sets):
    cmd = ["helm", "template", "x", CHART, "--set", f"aws.cluster_name={CLUSTER}",
           "--set", "aws.region=us-west-2", "--set", "global.ingress_domain_name=x.example"]
    for s in sets:
        cmd += ["--set", s]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def by_kind(docs, kind):
    return [d for d in docs if d.get("kind") == kind]


def api_group(d):
    """The API group of a rendered object: the part of apiVersion before the "/"."""
    return d.get("apiVersion", "").split("/")[0]


def is_ack(d):
    return api_group(d).endswith(".services.k8s.aws")


def is_upbound(d):
    return api_group(d).endswith(".upbound.io")


def ack_kind(docs, kind):
    return [d for d in by_kind(docs, kind) if is_ack(d)]


def upbound(docs):
    return [d for d in docs if is_upbound(d)]


@pytest.fixture(scope="module")
def ack():
    return render("clientProvisioner.identityBackend=ack")


@pytest.fixture(scope="module")
def crossplane():
    return render()  # default


def test_ack_backend_renders_no_crossplane_object(ack):
    assert upbound(ack) == []


def test_default_backend_still_crossplane_for_kind_crossplane_and_byoc(crossplane):
    kinds = sorted(d["kind"] for d in upbound(crossplane))
    assert kinds == ["PodIdentityAssociation", "Role"]
    assert not [d for d in crossplane if is_ack(d)]


def test_ack_role_name_namespace_wave_and_selector_scope(ack):
    (role,) = ack_kind(ack, "Role")
    assert role["apiVersion"] == "iam.services.k8s.aws/v1alpha1"
    # IAMRoleSelectors are keyed on namespaceSelector.names = <cluster name>
    assert role["metadata"]["namespace"] == CLUSTER
    assert role["spec"]["name"] == ROLE_NAME
    ann = role["metadata"]["annotations"]
    assert ann["argocd.argoproj.io/sync-wave"] == "1"
    assert ann["argocd.argoproj.io/sync-options"] == "SkipDryRunOnMissingResource=true"
    assert ann["services.k8s.aws/region"] == "us-west-2"
    assert ann["services.k8s.aws/adoption-policy"] == "adopt-or-create"
    # no retain: task destroy must be able to delete this cluster-prefixed role
    assert "services.k8s.aws/deletion-policy" not in ann


def test_ack_pia_wave_namespace_and_role_reference(ack):
    (pia,) = ack_kind(ack, "PodIdentityAssociation")
    assert pia["apiVersion"] == "eks.services.k8s.aws/v1alpha1"
    assert pia["metadata"]["namespace"] == CLUSTER
    assert pia["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "2"
    spec = pia["spec"]
    assert spec["clusterName"] == CLUSTER
    assert spec["namespace"] == "keycloak"
    assert spec["serviceAccount"] == "keycloak-client-provisioner"
    (role,) = ack_kind(ack, "Role")
    assert spec["roleRef"]["from"]["name"] == role["metadata"]["name"]


def test_service_account_unchanged_and_in_keycloak_namespace(ack):
    sa = [d for d in by_kind(ack, "ServiceAccount") if d["metadata"]["name"] == "keycloak-client-provisioner"]
    assert len(sa) == 1 and sa[0]["metadata"]["namespace"] == "keycloak"
    assert sa[0]["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "1"


def test_trust_and_permissions_identical_to_crossplane_backend(ack, crossplane):
    (arole,) = ack_kind(ack, "Role")
    (xrole,) = [d for d in upbound(crossplane) if d["kind"] == "Role"]
    xspec = xrole["spec"]["forProvider"]
    assert json.loads(arole["spec"]["assumeRolePolicyDocument"]) == json.loads(xspec["assumeRolePolicy"])
    (xinline,) = xspec["inlinePolicy"]
    assert list(arole["spec"]["inlinePolicies"]) == [xinline["name"]]
    assert json.loads(arole["spec"]["inlinePolicies"][xinline["name"]]) == json.loads(xinline["policy"])
    # same IAM role name as before (the crossplane external-name)
    assert xrole["metadata"]["annotations"]["crossplane.io/external-name"] == ROLE_NAME
    assert arole["spec"]["name"] == ROLE_NAME


def test_ack_tags_keep_ownership_labels(ack):
    (role,) = ack_kind(ack, "Role")
    tags = {t["key"]: t["value"] for t in role["spec"]["tags"]}
    assert tags == {"platform.gitops.io/role": "keycloak-client-provisioner",
                    "platform.gitops.io/cluster": CLUSTER}


def test_unknown_backend_fails_closed():
    with pytest.raises(subprocess.CalledProcessError):
        render("clientProvisioner.identityBackend=bogus")


def test_registry_selects_ack_only_for_kro_ack_provider():
    text = open(REGISTRY).read()
    assert "identityBackend" in text
    line = next(l for l in text.splitlines() if "identityBackend" in l)
    assert 'eq (index .metadata.labels "provider" | default "") "kro-ack"}}ack{{else}}crossplane{{end}}' in line


def test_chart_comment_no_longer_claims_no_new_ordering_constraint():
    text = open(IDENTITY_TPL).read()
    assert "introduces no new ordering constraint" not in text
    assert "crossplane-base" in text


@pytest.mark.parametrize("backend", ["ack", "crossplane"])
def test_policy_absolute_content_is_pinned(ack, crossplane, backend):
    """Parity alone misses a drift applied to both backends: pin the actual grants."""
    docs = ack if backend == "ack" else crossplane
    if backend == "ack":
        (role,) = ack_kind(docs, "Role")
        trust = json.loads(role["spec"]["assumeRolePolicyDocument"])
        (policy,) = role["spec"]["inlinePolicies"].values()
    else:
        (role,) = [d for d in upbound(docs) if d["kind"] == "Role"]
        trust = json.loads(role["spec"]["forProvider"]["assumeRolePolicy"])
        policy = role["spec"]["forProvider"]["inlinePolicy"][0]["policy"]
    (ts,) = trust["Statement"]
    assert ts["Principal"] == {"Service": "pods.eks.amazonaws.com"}
    assert sorted(ts["Action"]) == ["sts:AssumeRole", "sts:TagSession"]
    # only the hub's keycloak/keycloak-client-provisioner can use it (Pod Identity session tags)
    assert ts["Condition"] == {"StringEquals": {
        "aws:RequestTag/eks-cluster-name": CLUSTER,
        "aws:RequestTag/kubernetes-namespace": "keycloak",
        "aws:RequestTag/kubernetes-service-account": "keycloak-client-provisioner"}}
    (ps,) = json.loads(policy)["Statement"]
    assert ps["Effect"] == "Allow"
    assert sorted(ps["Action"]) == ["secretsmanager:CreateSecret", "secretsmanager:DescribeSecret",
                                    "secretsmanager:PutSecretValue"]
    assert ps["Resource"] == "arn:aws:secretsmanager:us-west-2:*:secret:*/oidc/*"


def test_trust_follows_a_renamed_service_account():
    docs = render("clientProvisioner.identityBackend=ack", "clientProvisioner.serviceAccountName=other-sa")
    (role,) = ack_kind(docs, "Role")
    (ts,) = json.loads(role["spec"]["assumeRolePolicyDocument"])["Statement"]
    assert ts["Condition"]["StringEquals"]["aws:RequestTag/kubernetes-service-account"] == "other-sa"
