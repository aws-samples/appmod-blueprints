"""Per-cluster Helm release names built by the appset-chart stay within Helm's 53 characters.

The appset-chart names the additionalResources / pod-identity sources
"<cluster>-<suffix>". With a long cluster name (peeks-spoke-staging is 19 characters)
"<cluster>-aws-for-fluentbit-credential-check" is 54 characters and `helm template`
refuses it. The name must stay "<cluster>-<suffix>" when it fits (existing installs keep
their release) and otherwise be cut to 53 characters with a hash of the cluster name.
The Argo CD go-template is re-evaluated here in Python (same arithmetic, sha256).
"""
import hashlib
import os
import re
import shutil
import subprocess

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
APPSET = os.path.join(REPO, "platform-charts", "appset-chart")
REG = os.path.join(REPO, "gitops", "addons", "registry")
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")

GUARD = re.compile(
    r"releaseName: '\{\{ if gt \(len \.name\) (\d+) \}\}\{\{ printf \"%s-%s-([a-z0-9-]+)\" "
    r"\(trunc (\d+) \.name \| trimSuffix \"-\"\) \(sha256sum \.name \| trunc 6\) \}\}"
    r"\{\{ else \}\}\{\{ \.name \}\}-([a-z0-9-]+)\{\{ end \}\}'")


def rendered():
    args = [HELM, "template", "cluster-addons", APPSET, "-f", os.path.join(APPSET, "values.yaml")]
    for n in ("_defaults", "core", "gitops", "security", "observability", "platform", "ml"):
        args += ["-f", os.path.join(REG, n + ".yaml")]
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def evaluate(m, name):
    limit, suffix, keep = int(m.group(1)), m.group(2), int(m.group(3))
    if len(name) > limit:
        cut = name[:keep].rstrip("-")
        return "%s-%s-%s" % (cut, hashlib.sha256(name.encode()).hexdigest()[:6], suffix)
    return "%s-%s" % (name, suffix)


@needs_helm
def test_cluster_release_names_fit_helm_limit():
    out = rendered()
    assert "releaseName: '{{ .name }}-" not in out, "unguarded <cluster>-<suffix> release name"
    found = list(GUARD.finditer(out))
    suffixes = {m.group(2) for m in found}
    assert {"aws-for-fluentbit-credential-check", "lbc-credential-check",
            "external-dns-credential-check", "eso-credential-check"} <= suffixes
    for m in found:
        assert m.group(2) == m.group(4)
        for name in ("peeks-spoke-dev", "peeks-spoke-prod", "peeks-spoke-staging",
                     "peeks-spoke-staging-eu-west-1x", "a" * 30, "a" * 52):
            rn = evaluate(m, name)
            assert len(rn) <= 53, (name, rn)
            if len(name) + 1 + len(m.group(2)) <= 53:
                assert rn == name + "-" + m.group(2), "short names must keep their release"


@needs_helm
def test_distinct_long_names_get_distinct_releases():
    m = next(GUARD.finditer(rendered()))
    a = evaluate(m, "peeks-spoke-staging-one")
    b = evaluate(m, "peeks-spoke-staging-two")
    assert a != b and len(a) <= 53 and len(b) <= 53
