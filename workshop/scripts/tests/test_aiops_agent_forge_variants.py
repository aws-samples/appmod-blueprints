"""`helm template` tests for the aiops-agent forge variants (GitLab / no forge).

chart/files/aiops-agent-app.yaml is a forge-neutral core with REPLACE_FORGE_<SLOT> tokens;
templates/application.yaml fills each from chart/files/forge/<forge>/<slot>.txt. The forge is
DERIVED (templates/_helpers.tpl "aiops-agent.forge") from values the registry entry already
injects from cluster annotations: gitlabDomain (gitlab_domain_name) and fleetRepoUrl
(overlay_repo_url, else a separate fleetRepoURL). No new parameter.

- gitlab: the workshop. gitlab-mcp, its token ExternalSecret and the incident path stay.
- none:   no GitLab forge for the fleet repo. No gitlab-mcp, no token ExternalSecret, no
          incident path; the agent lists skills-mcp + eks-read-mcp only (OAP /ready requires
          every configured mcpServers entry), and its prompt says it is read-only.

Run:  python -m pytest workshop/scripts/tests/test_aiops_agent_forge_variants.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "workshop", "aiops-agent", "chart")
CORE = os.path.join(CHART, "files", "aiops-agent-app.yaml")
FORGE_DIR = os.path.join(CHART, "files", "forge")
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm not on PATH")

GL = "gitlab.example.invalid"
WORKSHOP = {"accountId": "111111111111", "clusterPrefix": "peeks", "gitlabDomain": GL,
            "fleetRepoUrl": f"https://{GL}/user1/fleet-config.git"}
NO_FORGE = {"accountId": "111111111111", "clusterPrefix": "example-b", "gitlabDomain": "",
            "fleetRepoUrl": "https://github.com/example-org/fleet-config.git"}

LINE_SLOTS = ["AGENT_DEPENDS", "MCP_SERVERS", "WRITE_COMPONENT", "ACCESS_DEPENDS",
              "INCIDENT_PATH"]
PROMPT_SLOTS = ["PROMPT_INCIDENT_FIX", "PROMPT_WRITE_RULE", "PROMPT_TOOL_NOTES",
                "PROMPT_IDEMPOTENCY", "PROMPT_ACT_FIRST"]
BRIDGE_COMPONENTS = {"incident-bridge-selectors", "incident-bridge-aws", "amp-incident",
                     "incident-bridge"}


def render(tmp_path, values):
    f = tmp_path / "v.yaml"
    f.write_text(yaml.safe_dump(values))
    r = subprocess.run([HELM, "template", "aiops-agent", CHART, "-f", str(f)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def oam_app(out):
    apps = [d for d in yaml.safe_load_all(out)
            if d and d.get("kind") == "Application" and d["apiVersion"].startswith("core.oam")]
    assert len(apps) == 1
    return apps[0]


def components(out):
    return {c["name"]: c for c in oam_app(out)["spec"]["components"]}


def objects(comps):
    for c in comps.values():
        for o in (c.get("properties") or {}).get("objects") or []:
            yield c["name"], o


# ---------------------------------------------------------------- forge derivation
@needs_helm
@pytest.mark.parametrize("domain,url,forge", [
    (GL, f"https://{GL}/user1/fleet-config.git", "gitlab"),   # workshop
    (GL.upper(), f"https://{GL}/user1/fleet-config", "gitlab"),  # host compare is case-insensitive
    (GL, f"https://{GL}:8443/user1/fleet-config", "gitlab"),  # port is not part of the host
    (GL, f"git@{GL}:user1/fleet-config.git", "gitlab"),       # scp-like URL
    (GL, "", "gitlab"),                                         # GitLab, fleet repo not wired
    (GL, "https://github.com/example-org/fleet-config.git", "none"),  # fleet repo elsewhere
    ("", "https://github.com/example-org/fleet-config.git", "none"),  # no GitLab domain, fleet repo elsewhere
    ("", f"https://{GL}/user1/fleet-config.git", "none"),     # no gitlab_domain_name
    ("", "", "none"),
])
def test_forge_is_derived_from_existing_values(tmp_path, domain, url, forge):
    comps = components(render(tmp_path, {**NO_FORGE, "gitlabDomain": domain,
                                         "fleetRepoUrl": url}))
    assert ("gitlab-mcp" in comps) == (forge == "gitlab")
    assert (BRIDGE_COMPONENTS <= set(comps)) == (forge == "gitlab")


# ---------------------------------------------------------------- core + fragments
def test_every_slot_is_in_the_core_once_and_has_a_fragment_per_forge():
    core = open(CORE, encoding="utf-8").read()
    for slot in LINE_SLOTS:
        assert core.count(f"REPLACE_FORGE_{slot}\n") == 1, slot
        assert re.search(rf"^REPLACE_FORGE_{slot}$", core, re.M), f"{slot} must be a line"
    for slot in PROMPT_SLOTS:
        assert core.count(f"REPLACE_FORGE_{slot}") == 1, slot
    assert len(re.findall(r"REPLACE_FORGE_[A-Z_]+", core)) == len(LINE_SLOTS + PROMPT_SLOTS)
    for forge in ("gitlab", "none"):
        names = sorted(os.listdir(os.path.join(FORGE_DIR, forge)))
        assert names == sorted(s.lower().replace("_", "-") + ".txt"
                               for s in LINE_SLOTS + PROMPT_SLOTS), forge


def test_core_has_no_gitlab_component_or_server():
    core = open(CORE, encoding="utf-8").read()
    assert "- name: gitlab-mcp" not in core
    assert "kind: ExternalSecret" not in core
    assert "name: incident-bridge" not in core
    assert "kind: AmpIncident" not in core


def test_prompt_fragments_are_safe_inside_the_double_quoted_scalar():
    for forge in ("gitlab", "none"):
        for slot in PROMPT_SLOTS:
            p = os.path.join(FORGE_DIR, forge, slot.lower().replace("_", "-") + ".txt")
            text = open(p, encoding="utf-8").read()
            if forge == "none":
                assert "\n" not in text, p           # one physical line, \n escapes only
            assert not re.search(r'(?<!\\)"', text), p  # every quote escaped


# ---------------------------------------------------------------- no-forge render
@needs_helm
def test_no_forge_renders_no_gitlab_mcp_token_or_incident_path(tmp_path):
    out = render(tmp_path, NO_FORGE)
    comps = components(out)
    assert set(comps) == {"skills-mcp", "aiops-agent-memory", "aiops-agent", "eks-read-access",
                          "eks-read-mcp", "chat-ui", "agent-access", "eks-access-selector"}
    kinds = {(o["kind"], o["metadata"]["name"]) for _, o in objects(comps)}
    assert not [k for k in kinds if k[0] == "ExternalSecret"]
    assert not [k for k in kinds if "gitlab" in k[1] or k[1].startswith("incident-bridge-")
                and k != ("IAMRoleSelector", "incident-bridge-eks")]
    groups = {o["apiVersion"].split("/")[0] for _, o in objects(comps)}
    assert not groups & {"sns.services.k8s.aws", "sqs.services.k8s.aws",
                         "prometheusservice.services.k8s.aws", "kro.run"}
    assert "REPLACE_" not in out
    # Parsed content (YAML comments dropped) never names the GitLab MCP or its secret.
    dumped = yaml.safe_dump(oam_app(out))
    assert "gitlab-mcp" not in dumped and "GITLAB_" not in dumped


@needs_helm
def test_no_forge_agent_is_ready_with_two_mcp_servers(tmp_path):
    agent = components(render(tmp_path, NO_FORGE))["aiops-agent"]
    # OAP /ready requires every configured mcpServers entry: this list decides readiness.
    assert [m["name"] for m in agent["properties"]["mcpServers"]] == ["skills-mcp",
                                                                       "eks-read-mcp"]
    assert agent["dependsOn"] == ["aiops-agent-memory", "skills-mcp", "eks-read-mcp"]


@needs_helm
def test_no_forge_prompt_is_read_only_text_remediation(tmp_path):
    sm = components(render(tmp_path, NO_FORGE))["aiops-agent"]["properties"]["systemMessage"]
    assert "strictly READ-ONLY" in sm
    assert "minimal unified diff" in sm
    assert "`gitlab`" not in sm and "gitlab tool" not in sm.lower()
    assert "Idempotency" not in sm
    for kept in ("# Hard boundaries", "# GitOps remediation", "# Skills index"):
        assert kept in sm


@needs_helm
def test_no_forge_keeps_eks_routing_for_access_entries(tmp_path):
    comps = components(render(tmp_path, NO_FORGE))
    sel = comps["eks-access-selector"]["properties"]["objects"]
    assert [o["metadata"]["name"] for o in sel] == ["incident-bridge-eks"]
    assert sel[0]["spec"]["arn"] == "arn:aws:iam::111111111111:role/example-b-cluster-mgmt-eks"
    assert sel[0]["spec"]["resourceTypeSelector"] == [
        {"group": "eks.services.k8s.aws", "kind": "", "version": ""}]
    assert comps["agent-access"]["dependsOn"] == ["eks-access-selector"]


# ---------------------------------------------------------------- both variants
@needs_helm
@pytest.mark.parametrize("values", [WORKSHOP, NO_FORGE], ids=["gitlab", "none"])
def test_depends_on_only_names_rendered_components(tmp_path, values):
    comps = components(render(tmp_path, values))
    for name, c in comps.items():
        assert set(c.get("dependsOn") or []) <= set(comps), name


@needs_helm
def test_gitlab_variant_keeps_the_full_toolset(tmp_path):
    comps = components(render(tmp_path, WORKSHOP))
    assert {"gitlab-mcp"} | BRIDGE_COMPONENTS <= set(comps)
    agent = comps["aiops-agent"]
    assert [m["name"] for m in agent["properties"]["mcpServers"]] == [
        "skills-mcp", "eks-read-mcp", "gitlab-mcp"]
    assert "gitlab-mcp" in agent["dependsOn"]
    assert "dependsOn" not in comps["agent-access"]
    es = [o for _, o in objects(comps) if o["kind"] == "ExternalSecret"]
    assert [o["metadata"]["name"] for o in es] == ["gitlab-mcp-token"]
    assert "`gitlab` tool" in agent["properties"]["systemMessage"]
