"""The hub:pivot manifest must keep string values strings under YAML 1.1.

hub:pivot serializes the kind EksCluster to JSON and converts it with yq to the YAML file it
commits to the overlay repo. Argo CD (and Kubernetes) parse YAML 1.1, where a bare `no`, `yes`
or `on` is a boolean, while yq writes YAML 1.2, where it is a string. A platformTags value such
as auto-delete: "no" (the self-paced default) was committed bare, reached the hub as false, and
the hub-self-adoption sync failed with ".spec.awsTags.auto-delete: expected string". This test
runs the exact yq command of the Taskfile on such a spec and loads the result with PyYAML (a
YAML 1.1 loader).

Run:  python -m pytest workshop/scripts/tests/test_pivot_manifest_yaml11.py -q
"""
import json
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
YQ = shutil.which("yq")
if not YQ:
    pytest.skip("yq not on PATH", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
LINE = re.compile(r"""yq -p=json -o=yaml '([^']*)' "\$WORK/hub-instance\.json" > "\$WORK/hub-instance\.yaml\"""")


def _pivot_expr():
    found = LINE.findall(open(TASKFILE).read())
    assert len(found) == 1, found
    return found[0]


def test_yaml11_booleans_stay_strings(tmp_path):
    spec = {
        "apiVersion": "kro.run/v1alpha1",
        "kind": "EksCluster",
        "metadata": {"name": "acme-hub", "namespace": "acme-hub"},
        "spec": {
            "awsTags": {"auto-delete": "no", "keep": "yes", "flag": "on", "n": "3"},
            "deletionPolicy": "retain",
            "publicAccessCIDRs": ["0.0.0.0/0"],
            "replicas": 2,
            "enabled": True,
        },
    }
    src = tmp_path / "hub-instance.json"
    src.write_text(json.dumps(spec))
    out = subprocess.run([YQ, "-p=json", "-o=yaml", _pivot_expr(), str(src)],
                         capture_output=True, text=True, check=True).stdout
    assert yaml.safe_load(out) == spec, out
