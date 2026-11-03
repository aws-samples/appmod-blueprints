"""Disabling the aiops-agent addon must tear its KubeVela Application down cleanly.

Failure this guards (disable step of the AIOps module): Argo CD deleted the Application and
every KubeVela child at once, so the incident-bridge IAMRoleSelectors (and the provisioning
role) were gone before ACK deleted the resources they route. The ACK CRs and the AmpIncident
then hung DELETING and a re-enable recreated nothing.

Checks, on the rendered chart (no cluster needed):
- The OAM Application filters the Argo CD tracking-id annotation, so KubeVela does not copy it
  onto its children and Argo CD owns only the Application.
- A garbage-collect policy deletes components in reverse dependsOn order.
- Every component holding a CR routed by an IAMRoleSelector of this Application depends
  (transitively) on the component holding that selector, and the AmpIncident depends on the
  provisioning role. Derived from the rendered selectors, nothing hardcoded per group.
- A simulation of KubeVela's dependency GC deletes selectors and roles only after everything
  that needs them.

Run:  python -m pytest workshop/scripts/tests/test_aiops_agent_teardown_order.py -q
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "workshop", "aiops-agent", "chart")
HELM = shutil.which("helm")
pytestmark = pytest.mark.skipif(HELM is None, reason="helm not on PATH")

TRACKING = "argocd.argoproj.io/tracking-id"


@pytest.fixture(scope="module")
def app():
    out = subprocess.check_output(
        [HELM, "template", "t", CHART, "--set", "accountId=111111111111",
         "--set", "gitlabDomain=gitlab.example.com",
         "--set", "fleetRepoUrl=https://gitlab.example.com/u/fleet-config.git"], text=True)
    docs = [d for d in yaml.safe_load_all(out) if d]
    apps = [d for d in docs if d.get("apiVersion", "").startswith("core.oam.dev/")
            and d.get("kind") == "Application"]
    assert len(apps) == 1
    return apps[0]


def comps(app):
    return {c["name"]: c for c in app["spec"]["components"]}


def objects(c):
    return (c.get("properties") or {}).get("objects") or []


def deps(c):
    return set(c.get("dependsOn") or [])


def closure(cs, name):
    seen, todo = set(), list(deps(cs[name]))
    while todo:
        d = todo.pop()
        if d not in seen:
            seen.add(d)
            todo.extend(deps(cs[d]))
    return seen


def test_tracking_id_not_propagated(app):
    keys = app["metadata"].get("annotations", {}).get("filter.oam.dev/annotation-keys", "")
    assert TRACKING in [k.strip() for k in keys.split(",")]


def test_gc_policy_dependency_order(app):
    gc = [p for p in app["spec"].get("policies") or [] if p.get("type") == "garbage-collect"]
    assert len(gc) == 1 and gc[0]["properties"]["order"] == "dependency"


def routed(app):
    """[(selector component, selector name, group, namespace)] from the rendered selectors."""
    out = []
    for name, c in comps(app).items():
        for o in objects(c):
            if o.get("kind") == "IAMRoleSelector":
                for g in o["spec"].get("resourceTypeSelector") or []:
                    for ns in o["spec"]["namespaceSelector"].get("names") or []:
                        out.append((name, o["metadata"]["name"], g["group"], ns))
    return out


def test_routed_crs_depend_on_their_selector(app):
    cs = comps(app)
    rules = routed(app)
    assert rules, "expected the incident-bridge IAMRoleSelectors"
    checked = 0
    for name, c in cs.items():
        for o in objects(c):
            group = o.get("apiVersion", "").split("/")[0]
            ns = o.get("metadata", {}).get("namespace")
            for sel_comp, sel, g, sel_ns in rules:
                if g == group and ns == sel_ns and name != sel_comp:
                    checked += 1
                    assert sel_comp in closure(cs, name), (
                        f"{name} holds {o['kind']} {o['metadata']['name']} routed by {sel} "
                        f"but does not depend on {sel_comp}")
    assert checked >= 4


def test_amp_incident_depends_on_provisioning_role(app):
    cs = comps(app)
    amp = [n for n, c in cs.items() if any(o.get("kind") == "AmpIncident" for o in objects(c))]
    roles = [n for n, c in cs.items() if any(
        o.get("kind") == "Role" and o.get("apiVersion", "").startswith("iam.services.k8s.aws/")
        and "cluster-mgmt" in o["metadata"]["name"] for o in objects(c))]
    assert amp and roles
    for a in amp:
        for r in roles:
            assert r in closure(cs, a)


def simulate_gc(cs):
    """KubeVela gc order=dependency: a component is deleted only once no component that
    dependsOn it (or consumes its outputs) still exists. Returns the deletion rounds."""
    left, rounds = set(cs), []
    outputs = {n: {o["name"] for o in c.get("outputs") or []} for n, c in cs.items()}
    def dependents(n):
        return {m for m in cs if m != n and (n in deps(cs[m]) or any(
            i.get("from") in outputs[n] for i in cs[m].get("inputs") or []))}
    while left:
        now = {n for n in left if not (dependents(n) & left)}
        assert now, f"dependency cycle in {left}"
        rounds.append(now)
        left -= now
    return rounds


def test_simulated_teardown_deletes_selectors_last(app):
    cs = comps(app)
    rounds = simulate_gc(cs)
    pos = {n: i for i, r in enumerate(rounds) for n in r}
    for sel_comp, _, _, _ in routed(app):
        for n in cs:
            if sel_comp in closure(cs, n):
                assert pos[n] < pos[sel_comp], (n, sel_comp, rounds)
