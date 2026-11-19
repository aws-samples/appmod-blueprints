"""Static test for the HuggingFaceModel RGD's service account: it gets AWS credentials
through EKS Pod Identity only.

The model role (`iamRole`) trusts only `pods.eks.amazonaws.com`, so the IRSA path
(`AssumeRoleWithWebIdentity`) can never succeed for it. An `eks.amazonaws.com/role-arn`
annotation on the service account made the pod identity webhook inject the IRSA
environment into download pods created before the Pod Identity association was usable,
and their S3 calls then failed with AccessDenied on AssumeRoleWithWebIdentity.

Run:  python -m pytest workshop/scripts/tests/test_huggingface_sa_pod_identity_only.py -q
Set HF_RGD=<path> to run the same checks against another copy of the RGD.
"""
import json
import os

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.environ.get("HF_RGD") or os.path.join(
    REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests",
    "huggingface", "rg-huggingface-model.yaml")


@pytest.fixture(scope="module")
def resources():
    with open(RGD) as f:
        rgd = yaml.safe_load(f)
    return {r["id"]: r["template"] for r in rgd["spec"]["resources"]}


def test_role_trusts_pod_identity_only(resources):
    trust = json.loads(resources["iamRole"]["spec"]["assumeRolePolicyDocument"])
    principals = [s["Principal"] for s in trust["Statement"] if s["Effect"] == "Allow"]
    assert principals == [{"Service": "pods.eks.amazonaws.com"}]


def test_service_account_has_no_irsa_annotation(resources):
    annotations = resources["serviceAccount"]["metadata"].get("annotations") or {}
    assert "eks.amazonaws.com/role-arn" not in annotations, (
        "the model role does not trust the cluster OIDC provider, so the IRSA "
        "annotation only produces AssumeRoleWithWebIdentity denials")


def test_pod_identity_association_binds_the_service_account(resources):
    pia = resources["podIdentity"]["spec"]
    sa = resources["serviceAccount"]["metadata"]
    assert pia["serviceAccount"] == sa["name"] == "${schema.metadata.name}-sa"
    assert pia["namespace"] == sa["namespace"] == "${schema.spec.namespace}"
    assert pia["roleARN"] == "${iamRole.status.ackResourceMetadata.arn}"


def test_workflow_runs_as_the_service_account(resources):
    spec = resources["downloadWorkflow"]["spec"]
    assert spec["serviceAccountName"] == "${serviceAccount.metadata.name}"


def test_service_account_still_waits_for_the_association(resources):
    # kro orders resources by template references: the SA must still be created after
    # the association (and therefore after the role it references).
    annotations = resources["serviceAccount"]["metadata"].get("annotations") or {}
    assert annotations.get("eks.amazonaws.com/pod-identity-association") == (
        "${podIdentity.status.ackResourceMetadata.arn}")
