"""aiops-agent registry entry lives UPSTREAM, disabled by default; the overlay only decides.

- gitops/addons/registry/platform.yaml defines the aiops-agent entry, gated by the
  enable_aiops_agent label (no label -> no Application), chart path workshop/aiops-agent/chart.
- The workshop overlay overrides.yaml no longer carries a copy of the entry.
- fleetRepoUrl is a DERIVED value: the exact overlayRepoURLGit resolution of
  gitops/bootstrap/addons.yaml (overlay_repo_url, else a separate fleetRepoURL, else "").
- The chart derives the MR project from fleetRepoUrl; the deprecated gitlabMrProject
  override still wins when set; empty fleetRepoUrl -> empty project (dup-check off).
- The cluster-addons appset-chart renders the aiops-agent ApplicationSet for a hub with
  NO overlay wired (base registry only).

Run:  python -m pytest workshop/scripts/tests/test_aiops_agent_registry_upstream.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REG = os.path.join(REPO, "gitops", "addons", "registry")
PLATFORM = os.path.join(REG, "platform.yaml")
ADDONS = os.path.join(REPO, "gitops", "bootstrap", "addons.yaml")
WS_OVERRIDES = os.path.join(REPO, "workshop", "overlay", "overlays", "environments",
                            "control-plane", "overrides.yaml")
CHART = os.path.join(REPO, "workshop", "aiops-agent", "chart")
APPSET = os.path.join(REPO, "platform-charts", "appset-chart")
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")


def load(p):
    with open(p) as f:
        return yaml.safe_load(f) or {}


def entry():
    return load(PLATFORM)["aiops-agent"]


def test_entry_upstream_and_gated_off_by_default():
    e = entry()
    assert e["path"] == "workshop/aiops-agent/chart"
    assert e["namespace"] == "aiops-agent"
    assert e["selector"] == {"matchExpressions": [
        {"key": "enable_aiops_agent", "operator": "In", "values": ["true"]}]}
    assert "gitlabMrProject" not in e["valuesObject"]
    # Image pins stay in the chart values.yaml (single source of truth).
    assert not {"imageRegistry", "imageTag", "images"} & set(e["valuesObject"])


def test_workshop_overlay_no_longer_copies_entry():
    assert "aiops-agent" not in load(WS_OVERRIDES)


def test_fleet_repo_url_is_the_bootstrap_overlay_resolution():
    with open(ADDONS) as f:
        appset = yaml.safe_load(f)
    vo = appset["spec"]["template"]["spec"]["sources"][2]["helm"]["valuesObject"]
    assert entry()["valuesObject"]["fleetRepoUrl"] == vo["overlayRepoURLGit"]


def render_chart(tmp_path, values):
    f = tmp_path / "v.yaml"
    f.write_text(yaml.safe_dump(values))
    r = subprocess.run([HELM, "template", "aiops-agent", CHART, "-f", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def mr_project(out):
    lines = out.splitlines()
    i = next(n for n, l in enumerate(lines) if l.strip() == "- name: GITLAB_MR_PROJECT")
    return yaml.safe_load(lines[i + 1].strip().split(":", 1)[1])


# The dup-check project only exists in the GitLab forge variant (incident-bridge is not
# rendered without a forge, see test_aiops_agent_forge_variants.py), so these renders carry
# the GitLab domain of the fleet repo, as the workshop does.
GL = "gitlab.example.invalid"


@needs_helm
@pytest.mark.parametrize("url,expected", [
    (f"https://{GL}/user1/fleet-config.git", "user1/fleet-config"),
    (f"https://{GL}/example-org/fleet-config", "example-org/fleet-config"),
    ("", ""),
])
def test_chart_derives_mr_project(tmp_path, url, expected):
    out = render_chart(tmp_path, {"fleetRepoUrl": url, "gitlabDomain": GL})
    assert mr_project(out) == expected


@needs_helm
def test_deprecated_override_wins(tmp_path):
    out = render_chart(tmp_path, {"fleetRepoUrl": f"https://{GL}/a/b.git", "gitlabDomain": GL,
                                  "gitlabMrProject": "group/explicit"})
    assert mr_project(out) == "group/explicit"


@needs_helm
def test_appset_rendered_without_overlay(tmp_path):
    files = ["values.yaml"] + [os.path.join(REG, n + ".yaml") for n in
             ("_defaults", "core", "gitops", "security", "observability", "platform", "ml")]
    args = [HELM, "template", "cluster-addons", APPSET]
    for f in files:
        args += ["-f", f if os.path.isabs(f) else os.path.join(APPSET, f)]
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    sets = [d for d in yaml.safe_load_all(r.stdout)
            if d and d.get("kind") == "ApplicationSet" and d["metadata"]["name"] == "aiops-agent"]
    assert len(sets) == 1
    sel = sets[0]["spec"]["generators"][0]["clusters"]["selector"]
    assert sel["matchExpressions"] == [
        {"key": "enable_aiops_agent", "operator": "In", "values": ["true"]}]
