"""Hermetic tests: the Kargo chart pin includes the base-path logo fix.

Kargo's UI in <= v1.11.4 hardcodes `/kargo-logo-white.png` (no base path), so behind the
`/kargo` base path the browser asks the platform ALB for `/kargo-logo-white.png` and gets a 404
(the logo is only served at /kargo/kargo-logo-white.png). Fixed upstream in akuity/kargo#7323,
backported to release-1.11 and first shipped in v1.11.5. Our basePath setting
(`kargo.api.basePath: /kargo`) is already the right knob; the pin has to be >= 1.11.5.

Checks: Chart.yaml pin >= 1.11.5, Chart.lock agrees, and (when helm and the packaged
dependency are available) the render still carries the /kargo base path.

Run:  python -m pytest workshop/scripts/tests/test_kargo_chart_basepath_logo.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "kargo")
REGISTRY = os.path.join(REPO, "gitops", "addons", "registry", "gitops.yaml")
LOGO_FIX = (1, 11, 5)


def _v(s):
    return tuple(int(x) for x in re.match(r"(\d+)\.(\d+)\.(\d+)", s).groups())


def _dep(path):
    doc = yaml.safe_load(open(path))
    return next(d for d in doc["dependencies"] if d["name"] == "kargo")


def test_pin_includes_the_base_path_logo_fix():
    pin = _dep(os.path.join(CHART, "Chart.yaml"))["version"]
    assert _v(pin) >= LOGO_FIX, pin
    assert _v(pin)[:2] == (1, 11), "stay on the 1.11 line (patch bump only)"


def test_lock_matches_the_pin():
    assert _dep(os.path.join(CHART, "Chart.lock"))["version"] == _dep(os.path.join(CHART, "Chart.yaml"))["version"]


def test_registry_keeps_the_kargo_base_path():
    text = open(REGISTRY).read()
    assert re.search(r"kargo:\n\s+api:\n\s+host:.*\n\s+basePath: /kargo\n", text)


def test_render_serves_under_the_base_path(tmp_path):
    if not shutil.which("helm"):
        pytest.skip("helm not available")
    pin = _dep(os.path.join(CHART, "Chart.yaml"))["version"]
    if not os.path.exists(os.path.join(CHART, "charts", f"kargo-{pin}.tgz")):
        pytest.skip("dependency not built (helm dependency build)")
    vals = tmp_path / "v.yaml"
    vals.write_text("global: {ingress_domain_name: example.test, insecure: 'true'}\n"
                    "kargo: {api: {host: example.test, basePath: /kargo, adminAccount: {passwordHash: x, tokenSigningKey: y}, tls: {enabled: false, terminatedUpstream: true},"
                    " ingress: {enabled: false}}}\n")
    out = subprocess.run(["helm", "template", "k", CHART, "-f", str(vals)],
                         capture_output=True, text=True, check=True).stdout
    assert 'API_BASE_PATH: "/kargo"' in out
    assert f"ghcr.io/akuity/kargo:v{pin}" in out
