#!/usr/bin/env python3
"""Generate the PEEKS OAP Agent AWS architecture diagram.

Renders the autonomous incident-remediation loop: the platform OBSERVES (AMP),
ALERTS (SNS->SQS), a read-only agent does RCA and PROPOSES a fix as a GitLab MR,
a human MERGES, and GitOps (ArgoCD) HEALS the fleet. The agent never mutates the
cluster directly.

Run:  python3 peeks-agent-architecture.py   (writes peeks-agent-architecture.png)
"""
from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import EKS
from diagrams.aws.integration import SimpleNotificationServiceSns as SNS
from diagrams.aws.integration import SimpleQueueServiceSqs as SQS
from diagrams.aws.network import CloudFront
from diagrams.aws.management import Cloudwatch
from diagrams.aws.security import IdentityAndAccessManagementIam as IAM
from diagrams.aws.ml import Bedrock
from diagrams.k8s.compute import Pod, Deploy
from diagrams.k8s.network import SVC
from diagrams.onprem.vcs import Gitlab
from diagrams.onprem.gitops import ArgoCD
from diagrams.onprem.monitoring import Prometheus
from diagrams.generic.blank import Blank

graph_attr = {
    "fontsize": "22",
    "labelloc": "t",
    "pad": "0.6",
    "nodesep": "0.6",
    "ranksep": "1.1",
    "bgcolor": "white",
    "splines": "spline",
}

with Diagram(
    "PEEKS OAP Agent — Autonomous Incident Remediation (AWS / EKS)",
    filename="peeks-agent-architecture",
    show=False,
    direction="LR",
    graph_attr=graph_attr,
):
    # ── User access edge ──
    with Cluster("User access (Keycloak-gated)"):
        cf = CloudFront("CloudFront")
        kc = Blank("Keycloak\n(OIDC / SSO)")

    # ── EKS fleet (workloads run here; ArgoCD heals here) ──
    with Cluster("Amazon EKS fleet"):
        hub = EKS("peeks-e2e-hub")
        sdev = EKS("spoke-dev")
        sprod = EKS("spoke-prod")
        fleet = [hub, sdev, sprod]

    # ── Observe & detect ──
    with Cluster("Observe & detect"):
        amp = Prometheus("Amazon Managed\nPrometheus\n(alerting rules)")
        sns = SNS("SNS topic")
        sqs = SQS("SQS\npeeks-agent-incidents")
        amp >> Edge(label="rule fires\n(OOMKill / ImagePull /\nCrashLoop / Unsched / PVC)") >> sns >> Edge(label="raw delivery") >> sqs

    # ── Agent plane (ns peeks-agent, on the hub) ──
    with Cluster("peeks-agent namespace (hub)"):
        bridge = Deploy("incident-bridge\n(SQS->A2A, subject dedup)")
        agent = Pod("peeks-agent\nStrands agent (READ-ONLY)")
        gw = SVC("AgentGateway\n(MCP router)")
        with Cluster("MCP tools"):
            skills = Pod("skills-mcp\n(manage-addons,\ntroubleshoot-*)")
            eksread = Pod("eks-read-mcp\n(read-only)")
            glmcp = Pod("gitlab-mcp\n(write)")
        bifrost = Pod("Bifrost\n(LLM gateway)")
        chat = Pod("a2a-chat-ui")

    # ── LLM inference ──
    bedrock = Bedrock("Amazon Bedrock")

    # ── GitOps action / heal ──
    with Cluster("GitOps remediation (human-in-the-loop)"):
        gitlab = Gitlab("GitLab\nuser1/fleet-config")
        human = Blank("Human\nreview + merge")
        argo = ArgoCD("ArgoCD\n(EKS capability)")

    # ── IAM / Pod Identity ──
    iam = IAM("EKS Pod Identity / IAM\n(read-only + SQS)")
    cw = Cloudwatch("CloudWatch\n(metrics / logs)")

    # ===== Flows =====
    # detection
    fleet >> Edge(label="scrape metrics", style="dashed", color="gray") >> amp
    sqs >> Edge(label="long-poll") >> bridge
    bridge >> Edge(label="forward incident\n(A2A JSON-RPC, 1 per subject)") >> agent

    # agent reasoning
    agent >> Edge(color="darkgreen") >> gw
    gw >> Edge(color="darkgreen") >> [skills, eksread, glmcp]
    eksread >> Edge(label="read-only", style="dashed", color="gray") >> hub
    eksread >> Edge(style="dashed", color="gray") >> cw
    agent >> Edge(label="inference") >> bifrost >> bedrock
    iam >> Edge(style="dotted", color="orange") >> agent
    iam >> Edge(style="dotted", color="orange") >> bridge

    # action + heal
    glmcp >> Edge(label="open Merge Request\n(GitOps fix, additive)", color="blue") >> gitlab
    gitlab >> Edge(label="review") >> human >> Edge(label="merge") >> gitlab
    gitlab >> Edge(label="reconcile fleet-config\noverlay") >> argo
    argo >> Edge(label="apply fix (HEAL)", color="blue") >> fleet

    # user access
    cf >> kc >> chat >> Edge(color="darkgreen") >> agent
