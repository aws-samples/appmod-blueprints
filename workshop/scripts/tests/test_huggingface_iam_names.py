"""Hermetic tests for the HuggingFace model IAM names: a stack with a non-default resource
prefix names its model roles and policies after its hub, so a second stack in the account
never adopts (and rewrites) the first stack's; the default prefix keeps the legacy names.

`helm template` renders platform-manifests-post with the values the platform.yaml registry
entry passes (global.*) and the control-plane overlay's model list. The RGD is read as YAML
and its kro expressions are checked as text. No cluster, no AWS.

Run:  python -m pytest workshop/scripts/tests/test_huggingface_iam_names.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "platform-manifests-post")
OVERLAY_VALUES = os.path.join(
    REPO, "gitops", "overlays", "environments", "control-plane", "platform-manifests-post",
    "values.yaml")
RGD = os.path.join(
    REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "huggingface",
    "rg-huggingface-model.yaml")
MODELS = ["gpt2-neuron", "mistral-7b-neuron", "tinyllama"]


def _render(prefix):
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    out = subprocess.run(
        ["helm", "template", "pmp", CHART, "-f", OVERLAY_VALUES,
         "--set", f"global.resourcePrefix={prefix}", "--set", f"global.clusterName={prefix}-hub",
         "--set-string", "global.accountId=111122223333", "--set", "global.region=us-west-2"],
        check=True, capture_output=True, text=True).stdout
    docs = [d for d in yaml.safe_load_all(out) if d and d.get("kind") == "HuggingFaceModel"]
    assert sorted(d["metadata"]["name"] for d in docs) == MODELS
    return {d["metadata"]["name"]: d["spec"] for d in docs}


def _rgd_nodes():
    rgd = yaml.safe_load(open(RGD))
    return rgd["spec"]["schema"]["spec"], {r["id"]: r["template"] for r in rgd["spec"]["resources"]}


def test_non_default_prefix_gets_its_own_iam_names():
    for spec in _render("kfr").values():
        assert spec["iamNamePrefix"] == "kfr-hub-"
        assert spec["s3Bucket"] == "kfr-ray-models-111122223333"
    # The default prefix renders no iamNamePrefix, so existing stacks keep their roles.
    for spec in _render("peeks").values():
        assert "iamNamePrefix" not in spec


def test_rgd_prefixes_only_the_iam_names():
    schema, nodes = _rgd_nodes()
    assert schema["iamNamePrefix"] == 'string | default=""'
    name = "${schema.spec.iamNamePrefix}${schema.metadata.name}"
    policy, role = nodes["s3Policy"], nodes["iamRole"]
    assert policy["spec"]["name"] == f"{name}-s3-policy"
    assert role["spec"]["name"] == f"{name}-role"
    # adopt-or-create must look up the same (prefixed) policy ARN it would create
    arn = yaml.safe_load(policy["metadata"]["annotations"]["services.k8s.aws/adoption-fields"])["arn"]
    assert arn == "arn:aws:iam::${schema.spec.accountId}:policy/" + f"{name}-s3-policy"
    # Kubernetes object names are unchanged
    assert policy["metadata"]["name"] == "${schema.metadata.name}-s3-policy"
    assert role["metadata"]["name"] == "${schema.metadata.name}-role"
