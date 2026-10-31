"""Hermetic tests: AMP spoke scrapers are named after the REAL spoke cluster.

The `spokeScrapers` map keys stay `spoke-dev` / `spoke-prod` (they name the Scraper CR, so
existing scrapers are not renamed). The scraper alias and the `cluster` external label of its
metrics come from `clusterName`, which the registry resolves from the spoke_<env>_cluster_name
annotation (recorded by seed-observability when the spoke is not <prefix>-spoke-<env>) and
defaults to <prefix>-spoke-<env>. In the workshop the output must be byte-identical to before.

Run:  python -m pytest workshop/scripts/tests/test_observability_scraper_names.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("helm"):
    pytest.skip("helm not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "observability-aws")
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry", "observability.yaml")
PREFIX = "acme"


def _spokes(names=None):
    """names: {'dev': real-name} to set clusterName; None leaves it unset (older registry)."""
    out = {}
    for env in ("dev", "prod"):
        real = (names or {}).get(env, f"{PREFIX}-spoke-{env}")
        entry = {"clusterArn": f"arn:aws:eks:us-west-2:111122223333:cluster/{real}",
                 "subnetIds": "subnet-1,subnet-2", "securityGroupIds": "sg-1"}
        if names is not None:
            entry["clusterName"] = real
        out[f"spoke-{env}"] = entry
    return out


def _render(tmp_path, spokes):
    vals = tmp_path / "values.yaml"
    vals.write_text(yaml.safe_dump({
        "resourcePrefix": PREFIX,
        "aws": {"region": "us-west-2", "accountId": "111122223333", "clusterName": f"{PREFIX}-hub"},
        "spokeScrapers": spokes}))
    res = subprocess.run(["helm", "template", "t", CHART, "-f", str(vals),
                          "-s", "templates/spoke-scrapers.yaml"],
                         capture_output=True, text=True, check=True)
    return res.stdout


def _docs(rendered):
    return {d["metadata"]["name"]: d for d in yaml.safe_load_all(rendered) if d}


def _label(doc):
    return re.search(r"cluster: (\S+)", doc["spec"]["forProvider"]["scrapeConfiguration"]).group(1)


def test_workshop_render_is_identical_with_or_without_cluster_name(tmp_path):
    without = _render(tmp_path, _spokes(None))
    with_name = _render(tmp_path, _spokes({}))
    assert without == with_name
    docs = _docs(without)
    assert set(docs) == {f"{PREFIX}-scraper-spoke-dev", f"{PREFIX}-scraper-spoke-prod"}
    d = docs[f"{PREFIX}-scraper-spoke-dev"]
    assert d["spec"]["forProvider"]["alias"] == f"{PREFIX}-spoke-dev"
    assert _label(d) == f"{PREFIX}-spoke-dev"


def test_non_workshop_names_alias_and_label_use_the_real_cluster(tmp_path):
    docs = _docs(_render(tmp_path, _spokes({"dev": f"{PREFIX}-dev", "prod": "custom-prod"})))
    # the CR name (identity) is unchanged; the alias and metric label are the real names
    assert set(docs) == {f"{PREFIX}-scraper-spoke-dev", f"{PREFIX}-scraper-spoke-prod"}
    dev, prod = docs[f"{PREFIX}-scraper-spoke-dev"], docs[f"{PREFIX}-scraper-spoke-prod"]
    assert dev["spec"]["forProvider"]["alias"] == f"{PREFIX}-dev" and _label(dev) == f"{PREFIX}-dev"
    assert prod["spec"]["forProvider"]["alias"] == "custom-prod" and _label(prod) == "custom-prod"
    assert dev["spec"]["forProvider"]["source"][0]["eks"][0]["clusterArn"].endswith(f"cluster/{PREFIX}-dev")


def test_registry_resolves_cluster_name_from_annotation_with_workshop_default():
    text = open(REGISTRY).read()
    for env in ("dev", "prod"):
        want = (f'clusterName: \'{{{{ or (index .metadata.annotations "spoke_{env}_cluster_name") '
                f'(printf "%s-spoke-{env}" .metadata.annotations.resource_prefix) }}}}\'')
        assert want in text, env
