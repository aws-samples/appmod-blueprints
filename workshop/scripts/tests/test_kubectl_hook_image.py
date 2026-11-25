"""Static test: every kubectl hook Job uses one version-pinned image that is not a bare
`bitnami/` Docker Hub reference.

`bitnami/kubectl:latest` (no registry host) resolves to Docker Hub, is a floating tag on a
third-party namespace, and the hook scripts need `/bin/sh` (distroless kubectl images such
as registry.k8s.io/kubectl have none). The hooks use one pinned, multi-arch image from
Amazon ECR Public that ships busybox sh.

Run:  python -m pytest workshop/scripts/tests/test_kubectl_hook_image.py -q
"""
import os
import re

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHARTS = os.path.join(REPO, "gitops", "addons", "charts")
IMAGE_RE = re.compile(r"public\.ecr\.aws/chainguard/kubectl:latest-dev@sha256:[0-9a-f]{64}")

# (values file, dotted key). Every site must carry the same pinned reference.
VALUES = [
    (os.path.join(CHARTS, "ack-pod-identity", "values.yaml"), "crdWait.image"),
    (os.path.join(CHARTS, "crossplane-pod-identity", "values.yaml"), "crdWait.image"),
    (os.path.join(CHARTS, "pod-identity-restart-hook", "values.yaml"), "image"),
    (os.path.join(CHARTS, "podidentity-pod-restart", "values.yaml"), "image"),
    (os.path.join(CHARTS, "crossplane-base", "values.yaml"), "kubectlImage"),
    (os.path.join(REPO, "workshop", "aiops-agent", "access-chart", "values.yaml"), "crdWait.image"),
]
# Chart dirs whose templates carry an in-template fallback to the same image.
TEMPLATE_DIRS = [os.path.dirname(v) for v, _ in VALUES]

# Known exception, tracked separately: the airflow addon (off by default) still points its
# bundled postgres at public.ecr.aws/bitnami, which no longer exists. Remove this entry when
# that is fixed; the test then also guards it.
ALLOWED_BITNAMI = {os.path.join("gitops", "addons", "configs", "airflow", "values.yaml")}


def _get(values_path, dotted):
    with open(values_path) as f:
        node = yaml.safe_load(f)
    for part in dotted.split("."):
        node = node[part]
    return node


@pytest.mark.parametrize("path,key", VALUES)
def test_values_pin_the_shared_image(path, key):
    assert IMAGE_RE.fullmatch(_get(path, key)), f"{path}: {key} is not the pinned kubectl image"


def test_all_sites_use_the_same_image():
    assert len({_get(p, k) for p, k in VALUES}) == 1


@pytest.mark.parametrize("chart_dir", TEMPLATE_DIRS)
def test_template_fallback_matches_values(chart_dir):
    expected = _get(*next(v for v in VALUES if os.path.dirname(v[0]) == chart_dir))
    for root, _, files in os.walk(os.path.join(chart_dir, "templates")):
        for name in files:
            text = open(os.path.join(root, name)).read()
            for m in re.finditer(r"public\.ecr\.aws/chainguard/kubectl\S*?(?=[\"\s}])", text):
                assert m.group(0) == expected, f"{name}: fallback differs from values.yaml"


def test_no_bare_bitnami_image_in_charts():
    pat = re.compile(r"(^|[\s\"'=:/])bitnami/[A-Za-z0-9._-]+(:|\s|$)", re.M)
    hits = []
    for top in ("gitops", "workshop", "platform"):
        for root, _, files in os.walk(os.path.join(REPO, top)):
            for name in files:
                if not name.endswith((".yaml", ".yml", ".tpl", ".cue")):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, REPO)
                if rel in ALLOWED_BITNAMI:
                    continue
                for n, line in enumerate(open(full, errors="ignore"), 1):
                    if pat.search(line) and not line.lstrip().startswith("#"):
                        hits.append(f"{rel}:{n}: {line.strip()}")
    assert not hits, "bitnami/ image reference(s) found:\n" + "\n".join(hits)
