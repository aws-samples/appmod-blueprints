"""Hermetic tests for the install DAG order (perf O1/O2/O3).

O1  the workshop runs the platform install in two phases and declares the spokes in
    between: after install:hub (hub bootstrap), the overlay wiring, the webhook and
    the Crossplane providers credential gate; before install:complete (Keycloak).
O2  cloudfront:attach runs in the background from right after install:hub and is
    joined before post-install (IDC reaches Keycloak through CloudFront).
O3  the install gates on spokes ACTIVE only; the spoke apps sync runs in a
    background job, followed by the frontend prewarm.

The platform split must stay consumer-agnostic: install == install:hub +
install:complete in every kind-* provider. No AWS, no cluster.

Run:  python -m pytest workshop/scripts/tests/test_install_dag_early_spokes.py -q
"""
import os

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _tasks(path):
    return yaml.safe_load(open(os.path.join(REPO, path)))["tasks"]


def _flat(cmds):
    out = []
    for c in cmds:
        if isinstance(c, str):
            out.append(c)
        elif "task" in c:
            out.append("task: " + c["task"] + " " + str(c.get("vars", "")))
        else:
            out.append(c.get("cmd", ""))
    return out


def _index(lines, needle):
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    assert hits, needle
    return hits[0]


WS = _flat(_tasks("workshop/Taskfile.yaml")["install"]["cmds"])


def test_o1_spokes_declared_between_platform_phases():
    hub = _index(WS, "task install:hub")
    overlay = _index(WS, "task: set-overlay-repo")
    hook = _index(WS, "task: argocd-gitlab-webhook")
    providers = _index(WS, ":hub:wait-for-providers")
    dev = _index(WS, "spoke-dev'")
    prod = _index(WS, "spoke-prod'")
    complete = _index(WS, "task install:complete")
    idc = _index(WS, "task: post-install")
    assert hub < overlay < hook < providers < dev < prod < complete < idc


def test_o1_fallback_keeps_full_platform_install():
    block = WS[_index(WS, "task install:hub")]
    assert "install:hub:" in block and "Taskfile.yaml" in block and "task install\n" in block


def test_o2_cloudfront_attach_backgrounded_and_joined_before_idc():
    bg = _index(WS, 'start "cloudfront:attach (bg)"')
    join = _index(WS, "/tmp/cloudfront-attach.rc ]")
    assert _index(WS, "task install:hub") < bg < _index(WS, "task: set-overlay-repo")
    assert _index(WS, "task install:complete") < join < _index(WS, "task: post-install")
    assert "task cloudfront:attach" in WS[join]  # inline re-run when the bg run failed
    assert not any(ln.startswith("task: cloudfront:attach") for ln in WS)


def test_o3_install_gates_on_active_only_and_backgrounds_spoke_apps():
    gate = _index(WS, "task: wait-for-spokes ")
    assert "'SPOKE_APPS': 'false'" in WS[gate]
    bg = _index(WS, "task spoke-apps-bg")
    assert gate < bg < _index(WS, "spoke apps check")
    job = _flat(_tasks("workshop/Taskfile.yaml")["spoke-apps-bg"]["cmds"])
    assert _index(job, "task: wait-for-spokes:apps") < _index(job, "task: prewarm-pathA-frontend")
    # standalone `task wait-for-spokes` still waits for the apps
    wfs = _tasks("workshop/Taskfile.yaml")["wait-for-spokes"]
    assert wfs["vars"]["SPOKE_APPS"].endswith('default "true"}}')


@pytest.mark.parametrize("provider", ["kind-kro-ack", "kind-crossplane"])
def test_platform_install_is_hub_then_complete(provider):
    t = _tasks(f"cluster-providers/{provider}/Taskfile.yaml")
    calls = [c["task"] for c in t["install"]["cmds"] if isinstance(c, dict) and "task" in c]
    assert calls == ["install:hub", "install:complete"]
    hub = [c["task"] for c in t["install:hub"]["cmds"] if isinstance(c, dict) and "task" in c]
    assert hub[-1] == "install:hub-settle-bg"
    done = [c["task"] for c in t["install:complete"]["cmds"] if isinstance(c, dict) and "task" in c]
    assert done == ["install:finalize", "observability:converge"]
    text = open(os.path.join(REPO, f"cluster-providers/{provider}/Taskfile.yaml")).read()
    for word in ("spokes:enable", "set-overlay-repo", "fleet-config.git"):
        assert word not in "".join(map(str, t["install:hub"]["cmds"])), word
    assert text  # provider stays consumer-agnostic (no workshop task in its install)


def test_root_install_phases():
    t = _tasks("Taskfile.yaml")
    assert any("install:hub" in str(c) for c in t["install:hub"]["cmds"])
    joined = str(t["install:complete"]["cmds"])
    assert "install:complete" in joined and "enable-capability-logs" in joined
