"""Hermetic tests for the CICDPipeline DORA deployment workflow on a PROD push
(cicd-pipeline.yaml, the `<name>-dora-deployment-workflow` WorkflowTemplate).

A prod push (gitlab-dora-prod-trigger, any commit touching deployment/prod/) runs
resolve-deployed-tag, then check-rollout-status and process-deployment. The module's PROD
manifest starts from the `httpd:alpine` placeholder, which is not this pipeline's image and is
never rolled out before the first promotion. The workflow must not wait for it (3 x 20 min of
check-rollout-status timeouts, then a Failed workflow and Error pods) nor record it in DevLake:

- resolve-deployed-tag prints the tag only for an image from the pipeline's own ECR repository;
- check-rollout and process-and-send-deployment are skipped when it printed nothing (an empty
  tag would otherwise match any running image, since check-rollout-status tests
  `*"$COMMIT_HASH"*`).

The step script is read verbatim from the RGD, its kro and Argo parameters are filled in, and it
runs with bash. `curl` is a fake GitLab files API that serves the pushed manifest. No cluster, no
network.

Run:  python -m pytest workshop/scripts/tests/test_dora_prod_skip_placeholder.py -q
"""
import json
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
for _tool in ("bash", "jq", "sed", "awk", "grep"):
    if not shutil.which(_tool):
        pytest.skip(f"{_tool} not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RGD = os.path.join(REPO, "gitops", "addons", "charts", "kro", "resource-groups", "manifests",
                   "cicd-pipeline", "cicd-pipeline.yaml")
ECR = "123456789012.dkr.ecr.us-west-2.amazonaws.com/peeks/java"
SHA = "8e82388" + "0" * 33
AFTER = "b" * 40

FAKE_CURL = """#!/bin/bash
# Fake GitLab: any repository/files/<f>/raw request returns $FAKE_MANIFEST
for a in "$@"; do case "$a" in *repository/files/*/raw*) cat "$FAKE_MANIFEST"; exit 0;; esac; done
exit 22
"""


def _doradeploy():
    with open(RGD) as f:
        rgd = yaml.safe_load(f)
    res = next(r for r in rgd["spec"]["resources"] if r["id"] == "doradeploy")
    return res["template"]["spec"]


def _template(name):
    return next(t for t in _doradeploy()["templates"] if t["name"] == name)


def _resolve(tmp_path, manifest, environment="PRODUCTION"):
    src = _template("resolve-deployed-tag")["script"]["source"]
    src = (src.replace("${schema.spec.gitlab.hostname}", "gitlab.test")
              .replace("${ecrmainrepo.status.repositoryURI}", ECR)
              .replace("{{workflow.parameters.environment}}", environment))
    assert "${" not in src.replace("$ENV", ""), "unresolved kro reference left in the script"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)
    mf = tmp_path / "application.yaml"
    mf.write_text(manifest)
    body = json.dumps({
        "after": AFTER, "project": {"id": 42},
        "commits": [{"id": AFTER, "added": ["deployment/prod/application.yaml"], "modified": []}],
    })
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", BODY=body,
               GITLAB_TOKEN="t", FAKE_MANIFEST=str(mf))
    script = tmp_path / "resolve.sh"
    script.write_text(src)
    p = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True,
                       cwd=tmp_path, timeout=30)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip(), p.stderr


KUBEVELA = """apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  annotations:
    app.oam.dev/publishVersion: "{pv}"
spec:
  components:
    - name: java-webservice
      properties:
        image: {image}
"""


def test_placeholder_image_resolves_to_no_tag(tmp_path):
    tag, err = _resolve(tmp_path, KUBEVELA.format(pv="placeholder", image="httpd:alpine"))
    assert tag == ""
    assert "not from this pipeline's ECR repository" in err


def test_quoted_placeholder_image_resolves_to_no_tag(tmp_path):
    tag, _ = _resolve(tmp_path, KUBEVELA.format(pv="placeholder", image='"httpd:alpine"'))
    assert tag == ""


def test_promoted_app_image_resolves_to_its_tag(tmp_path):
    tag, _ = _resolve(tmp_path, KUBEVELA.format(pv=SHA, image=f"{ECR}:{SHA}"))
    assert tag == SHA


def test_initial_tag_from_own_repo_is_kept(tmp_path):
    tag, _ = _resolve(tmp_path, KUBEVELA.format(pv="initial", image=f"{ECR}:initial"))
    assert tag == "initial"


def test_image_from_another_ecr_repo_is_not_recorded(tmp_path):
    other = "123456789012.dkr.ecr.us-west-2.amazonaws.com/peeks/rust"
    tag, _ = _resolve(tmp_path, KUBEVELA.format(pv=SHA, image=f"{other}:{SHA}"))
    assert tag == ""


def test_dev_push_still_uses_the_commit_sha(tmp_path):
    tag, _ = _resolve(tmp_path, KUBEVELA.format(pv="x", image="httpd:alpine"),
                      environment="DEVELOPMENT")
    assert tag == AFTER


def test_rollout_check_and_devlake_record_skip_on_empty_tag():
    steps = next(t for t in _doradeploy()["templates"]
                 if t["name"] == "handle-rollout-check-and-process-deploy")["steps"]
    by_name = {s["name"]: s for group in steps for s in group}
    expr = "'{{steps.resolve-tag.outputs.result}}' != ''"
    assert by_name["check-rollout"].get("when") == expr
    assert by_name["process-and-send-deployment"].get("when") == expr
    assert "when" not in by_name["resolve-tag"]
