"""Hermetic tests: the pre-staged HuggingFace models are a workshop feature.

The model download Workflows upload to <resource_prefix>-ray-models-<account>, a bucket
only the workshop install creates (`<provider>:ray:setup`). So:

* a generic hub (chart defaults + the generic control-plane overlay) renders NO
  HuggingFaceModel, and must not start downloads toward a bucket nobody creates;
* the workshop, which layers its own overlay (workshop/overlay/, seeded to the
  fleet-config root and read as $overlay/overlays/environments/<env>/<addon>/values.yaml),
  still renders the 3 models;
* the RGD's wait-bucket step polls in ONE pod (a failed run no longer leaves one Failed
  pod per retry attempt) and the instance is Ready only once the Workflow Succeeded;
* the dead `modelS3Bucket.enabled` config key is gone, and the workshop's
  create-ray-models-bucket uses the same bucket name as the chart.

`helm template` renders platform-manifests-post with the same valueFiles order as the
platform.yaml registry entry (defaults chart values, $defaults env overlay, $overlay env
overlay). No cluster, no AWS.

Run:  python -m pytest workshop/scripts/tests/test_ray_models_workshop_overlay.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "platform-manifests-post")
ADDON = "platform-manifests-post"
GENERIC_ENV_OVERLAY = os.path.join(
    REPO, "gitops", "overlays", "environments", "control-plane", ADDON, "values.yaml")
WORKSHOP_ENV_OVERLAY = os.path.join(
    REPO, "workshop", "overlay", "overlays", "environments", "control-plane", ADDON,
    "values.yaml")
RGD = os.path.join(
    REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests", "huggingface",
    "rg-huggingface-model.yaml")
MODELS = ["gpt2-neuron", "mistral-7b-neuron", "tinyllama"]


def _render(*value_files):
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    cmd = ["helm", "template", "pmp", CHART]
    # ArgoCD renders with ignoreMissingValueFiles: true, so a missing layer is skipped.
    for f in value_files:
        if os.path.exists(f):
            cmd += ["-f", f]
    cmd += ["--set", "global.resourcePrefix=kfr", "--set", "global.clusterName=kfr-hub",
            "--set-string", "global.accountId=111122223333", "--set", "global.region=us-west-2"]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d and d.get("kind") == "HuggingFaceModel"]


def test_generic_hub_renders_no_models():
    assert _render(GENERIC_ENV_OVERLAY) == []


def test_generic_overlay_declares_no_models():
    if os.path.exists(GENERIC_ENV_OVERLAY):
        vals = yaml.safe_load(open(GENERIC_ENV_OVERLAY)) or {}
        assert not vals.get("huggingfaceModels")


def test_workshop_overlay_keeps_the_three_models():
    docs = _render(GENERIC_ENV_OVERLAY, WORKSHOP_ENV_OVERLAY)
    assert sorted(d["metadata"]["name"] for d in docs) == MODELS
    for d in docs:
        assert d["spec"]["s3Bucket"] == "kfr-ray-models-111122223333"


def test_workshop_overlay_is_on_the_appset_overlay_path():
    # The appset chart reads $overlay/<basepath>overlays/environments/<env>/<addon>/values.yaml;
    # workshop/overlay/ is copied to the fleet-config root (basepath "").
    tpl = open(os.path.join(REPO, "platform-charts", "appset-chart", "templates",
                            "_application_set.tpl")).read()
    assert "overlays/environments/{{`{{.metadata.labels.environment}}`}}/{{ $nameNormalize }}" in tpl
    taskfile = open(os.path.join(REPO, "workshop", "Taskfile.yaml")).read()
    assert 'cp -r "$WORKSHOP_DIR/workshop/overlay/." "$TMP/"' in taskfile


def _rgd_resources():
    rgd = yaml.safe_load(open(RGD))
    return {r["id"]: r for r in rgd["spec"]["resources"]}


def _wf_template(name):
    wf = _rgd_resources()["downloadWorkflow"]["template"]["spec"]
    return wf, next(t for t in wf["templates"] if t["name"] == name)


def test_wait_bucket_polls_in_one_pod():
    wf, wait = _wf_template("wait-bucket")
    # No per-attempt pod storm: retries only on pod-level errors, a handful at most.
    rs = wait.get("retryStrategy", {})
    assert rs.get("retryPolicy") == "OnError"
    assert int(rs.get("limit", 0)) <= 3
    script = wait["container"]["args"][0]
    assert "while" in script and "head-bucket" in script and "exit 1" in script
    # Failed runs stay debuggable, succeeded runs are fully reaped.
    assert wf["podGC"]["strategy"] == "OnWorkflowSuccess"


def test_instance_ready_only_when_workflow_succeeded():
    ready = _rgd_resources()["downloadWorkflow"].get("readyWhen", [])
    assert '${downloadWorkflow.status.?phase.orValue("") == "Succeeded"}' in ready


def test_dead_model_s3_bucket_key_removed():
    for rel in ("config.yaml", os.path.join("workshop", "create-config.sh")):
        assert "modelS3Bucket" not in open(os.path.join(REPO, rel)).read(), rel


def test_workshop_bucket_name_matches_chart():
    taskfile = open(os.path.join(REPO, "workshop", "Taskfile.yaml")).read()
    assert "{{.HUB_CLUSTER_NAME}}-ray-models-" not in taskfile
    assert 'BUCKET="{{.RESOURCE_PREFIX}}-ray-models-{{.AWS_ACCOUNT_ID}}"' in taskfile
