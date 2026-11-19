"""Static test for the CICDPipeline RGD's service account: it gets AWS credentials through
EKS Pod Identity only.

The pipeline role (`iamrole`) trusts only `pods.eks.amazonaws.com`, so the IRSA path
(`AssumeRoleWithWebIdentity`) can never succeed for it. An `eks.amazonaws.com/role-arn`
annotation on the service account made the pod identity webhook inject the IRSA
environment into pods created before the Pod Identity association was usable; their
`aws ecr get-login-password` then failed with AccessDenied on AssumeRoleWithWebIdentity.

Run:  python -m pytest workshop/scripts/tests/test_cicd_sa_pod_identity_only.py -q
Set CICD_RGD=<path> to run the same checks against another copy of the RGD.
"""
import json
import os

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.environ.get("CICD_RGD") or os.path.join(
    REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests",
    "cicd-pipeline", "cicd-pipeline.yaml")


@pytest.fixture(scope="module")
def resources():
    with open(RGD) as f:
        rgd = yaml.safe_load(f)
    return {r["id"]: r["template"] for r in rgd["spec"]["resources"]}


def test_role_trusts_pod_identity_only(resources):
    trust = json.loads(resources["iamrole"]["spec"]["assumeRolePolicyDocument"])
    principals = [s["Principal"] for s in trust["Statement"] if s["Effect"] == "Allow"]
    assert principals == [{"Service": "pods.eks.amazonaws.com"}]


def test_service_account_has_no_irsa_annotation(resources):
    annotations = resources["serviceaccount"]["metadata"].get("annotations") or {}
    assert "eks.amazonaws.com/role-arn" not in annotations, (
        "the pipeline role does not trust the cluster OIDC provider, so the IRSA "
        "annotation only produces AssumeRoleWithWebIdentity denials")


def test_pod_identity_association_binds_the_service_account(resources):
    pia = resources["podidentityassoc"]["spec"]
    sa = resources["serviceaccount"]["metadata"]
    assert pia["serviceAccount"] == sa["name"]
    # The SA has no explicit namespace, so kro creates it in the instance namespace.
    assert sa.get("namespace") in (None, pia["namespace"])
    assert pia["namespace"] == "${schema.metadata.namespace}"
    assert pia["roleARN"] == "${iamrole.status.ackResourceMetadata.arn}"


def test_service_account_still_waits_for_the_association(resources):
    # kro orders resources by template references: the SA must still be created after
    # the association (and therefore after the role it references).
    annotations = resources["serviceaccount"]["metadata"].get("annotations") or {}
    assert annotations.get("eks.amazonaws.com/pod-identity-association") == (
        "${podidentityassoc.status.ackResourceMetadata.arn}")
