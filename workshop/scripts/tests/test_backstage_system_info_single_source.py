"""Hermetic tests: the Backstage `system-info` System has ONE source, the dynamic ConfigMap.

The static platform/backstage/templates/catalog-info.yaml used to declare a second
`system-info` System whose values are unrendered `{{ values.* }}` placeholders. Backstage keys
entities by ref, so both locations claimed system:default/system-info. The dynamic one
(backstage-dynamic-catalog ConfigMap, real values) is the only one that must exist.

Checks: no static catalog file reachable from catalog-info.yaml declares it; the chart's
ConfigMap declares it exactly once and carries every spec field the templates read through
`fetchSystem`; the chart still loads that ConfigMap as a catalog location that allows System.

Run:  python -m pytest workshop/scripts/tests/test_backstage_system_info_single_source.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TEMPLATES = os.path.join(REPO, "platform", "backstage", "templates")
CHART = os.path.join(REPO, "gitops", "addons", "charts", "backstage")


def _reachable(path, seen=None):
    """Every local catalog file reachable through Location `targets`."""
    seen = seen if seen is not None else set()
    path = os.path.normpath(path)
    if path in seen or not os.path.exists(path):
        return seen
    seen.add(path)
    for doc in yaml.safe_load_all(open(path)):
        if doc and doc.get("kind") == "Location":
            for t in (doc.get("spec") or {}).get("targets", []):
                if not t.startswith("http"):
                    _reachable(os.path.join(os.path.dirname(path), t), seen)
    return seen


def _system_infos(files):
    found = []
    for f in files:
        for doc in yaml.safe_load_all(open(f)):
            if doc and doc.get("kind") == "System" and doc["metadata"]["name"] == "system-info":
                found.append(f)
    return found


def test_static_catalog_does_not_declare_system_info():
    files = _reachable(os.path.join(TEMPLATES, "catalog-info.yaml"))
    assert len(files) > 1, "expected catalog-info.yaml to reference other catalog files"
    assert _system_infos(files) == []


@pytest.fixture(scope="module")
def rendered():
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    out = subprocess.run(["helm", "template", "b", CHART, "-s", "templates/install.yaml"],
                         capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def test_dynamic_configmap_is_the_single_source_with_every_field_templates_read(rendered):
    cms = [d for d in rendered if d["kind"] == "ConfigMap"
           and d["metadata"]["name"] == "backstage-dynamic-catalog"]
    assert len(cms) == 1
    entities = [e for e in yaml.safe_load_all(cms[0]["data"]["dynamic-catalog.yaml"]) if e]
    assert [e["metadata"]["name"] for e in entities] == ["system-info"]
    spec = entities[0]["spec"]
    used = set()
    for root, _, names in os.walk(os.path.join(REPO, "platform", "backstage")):
        for n in names:
            if n.endswith((".yaml", ".yml")) and "skeleton" not in root:
                used |= set(re.findall(r"fetchSystem'\]\.output\.entity\.spec\.(\w+)",
                                       open(os.path.join(root, n)).read()))
    assert "gitlab_hostname" in used
    assert used <= set(spec), sorted(used - set(spec))


def test_chart_still_loads_the_dynamic_catalog_file_allowing_system(rendered):
    cfg = next(d for d in rendered if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "backstage-config")
    app = yaml.safe_load(cfg["data"]["app-config.yaml"])
    locs = app["catalog"]["locations"]
    dyn = [l for l in locs if l["type"] == "file" and l["target"] == "/app/catalog/dynamic-catalog.yaml"]
    assert len(dyn) == 1 and "System" in dyn[0]["rules"][0]["allow"]
