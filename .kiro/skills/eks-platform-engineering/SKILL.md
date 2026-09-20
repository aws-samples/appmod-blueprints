---
name: eks-platform-engineering
description: Use whenever someone is designing or building an Internal Developer Platform (IDP) or doing platform engineering on Amazon EKS — phrased as "build a developer platform", "self-service for developers", "golden paths", "IDP", or "set up Backstage / ArgoCD / Kargo". Covers the opinionated platform stack — developer portal (Backstage), GitOps delivery (ArgoCD, Argo Workflows), progressive delivery (Argo Rollouts) and multi-stage promotion (Kargo), infrastructure abstraction (ACK, kro), the developer-facing app abstraction (Backstage templates + kro, or KubeVela/OAM), self-service provisioning, hub-and-spoke topology with the GitOps Bridge, identity/SSO (Keycloak, Pod Identity), measuring success (DORA, Apache DevLake), GenAI-assisted platform engineering (Kiro), and golden paths for AI/ML and data. Trigger even if "platform engineering" is never said. Skip for single-cluster EKS architecture or cost/ops tuning with no platform angle (use eks-best-practices); for standalone Terraform use terraform-skill.
---

# EKS Platform Engineering

Guidance for designing and building an **Internal Developer Platform (IDP)** on Amazon EKS. This skill is opinionated: it teaches one proven, integrated golden-path stack end to end rather than cataloguing every option. The reference architecture and tool choices below are the recommended default; deviate only with a reason.

This is the "how do I build a platform that other teams self-serve from" skill. For "how do I run a single EKS cluster well" (compute, networking, security, cost, upgrades), use `eks-best-practices` instead.

## When to Use This Skill

**Activate when the user wants to:**
- Build or design an Internal Developer Platform / developer self-service on EKS
- Stand up or wire together a developer portal (Backstage), GitOps (ArgoCD/Argo Workflows), progressive delivery (Argo Rollouts), or promotion (Kargo)
- Define golden paths — standardized, paved ways for app teams to ship
- Abstract AWS resources behind Kubernetes (ACK, kro) or applications behind a developer-facing model (Backstage templates + kro, or OAM/KubeVela)
- Enable self-service environment or resource provisioning
- Measure platform success (DORA metrics)
- Use GenAI (Kiro) to author platform templates/manifests
- Extend the platform to AI/ML or data-engineering workloads

**Don't use this skill for:**
- Single-cluster EKS architecture, sizing, cost, or upgrade decisions with no self-service/platform angle → `eks-best-practices`
- Standalone Terraform/OpenTofu module authoring → `terraform-skill`
- Discovering what's already running on a cluster → `eks-recon`
- Generic Kubernetes concepts (Claude knows these)

## What Is an Internal Developer Platform

CNCF defines a platform as "an integrated collection of capabilities defined and presented according to the needs of the platform's users." An IDP packages tools, services, and automation so application, ML, and data teams **self-serve** — provisioning environments, resources, and deployments without tickets — while a platform team owns the paved paths and guardrails.

**Why it matters:** speed (faster delivery), control (safe, consistent operations), cost (economies of scale), and continuous improvement (shared golden paths). Platform engineering has moved from emerging trend to mainstream practice — Gartner's widely-cited forecast that 80% of large software organizations would stand up platform engineering teams by 2026 reflects how quickly the discipline has been adopted.

**The core principle — separation of concerns:**
- **Platform team** defines *how*: portal templates, the application abstraction (Backstage software templates + kro compositions, or OAM component/trait definitions), ACK controllers, CI/CD scaffolds, promotion stages, guardrails.
- **App/ML/data teams** choose *what*: pick a template, fill parameters, push code. They never touch raw Kubernetes or AWS APIs.

See [references/idp-architecture.md](references/idp-architecture.md) for the full reference architecture and the IDP value/challenge framework.

## The Opinionated Platform Stack

This is the recommended, integration-tested stack. Each layer has one default tool.

| Layer | Tool | Role |
|-------|------|------|
| **Developer portal** | Backstage | Self-service catalog + software templates (scaffolder) — the "front door" |
| **Identity / SSO** | Keycloak | One login (OIDC/SAML) federated across every platform tool |
| **GitOps CD** | ArgoCD | Reconciles cluster state from Git; deploys platform add-ons and apps |
| **CI / orchestration** | Argo Workflows (+ Argo Events) | Container-native build pipelines, webhook-triggered |
| **Progressive delivery** | Argo Rollouts | Canary/blue-green with functional, performance, and metrics gates + auto-rollback |
| **Multi-stage promotion** | Kargo | GitOps-native dev→prod promotion of the *same* artifact |
| **AWS resource provisioning** | ACK (AWS Controllers for K8s) | AWS resources (S3, DynamoDB, IAM, …) as Kubernetes CRDs |
| **Resource composition** | kro | Compose many resources into one CRD (e.g. `CICDPipeline`, `EKSCluster`) |
| **Application abstraction** | Backstage templates + kro | Developer-facing app model — a Backstage template gathers parameters and a kro `ResourceGraphDefinition` renders the underlying workload + dependencies (KubeVela/OAM is a supported alternative — see note) |
| **Secrets** | External Secrets Operator | Sync secrets from AWS Secrets Manager into clusters |
| **Identity for workloads** | EKS Pod Identity (recommended for new workloads) / IRSA | Credential-free AWS access from pods |
| **Observability / metrics** | Amazon Managed Grafana + Prometheus + Apache DevLake | Dashboards, app metrics, DORA metrics |
| **GenAI** | Kiro | Generate Backstage templates, kro/OAM compositions, and deployment manifests (Kiro is AWS's successor to Amazon Q Developer — see GenAI section) |

> **Maturity note on `kro`:** kro (which bundles many resources into one simple custom resource) is newer and less battle-tested than the rest of this stack — as of June 2026 it is at **v0.9.2 with a `v1alpha1` API** (pre-1.0; the maintainers note breaking changes may still land). It works well and is a Kubernetes SIG subproject, but confirm its current maturity fits your risk tolerance before you standardize on it. If you want a more established tool for the same job — composing AWS and Kubernetes resources behind one API — **Crossplane** is the proven alternative.
>
> **Application-abstraction choice:** the default above (Backstage templates + kro) keeps the platform on one composition engine. **KubeVela / OAM** is a fully supported alternative that gives a richer `Application` model (Components + Traits) — choose it if you want that abstraction, but note its current velocity before standardizing on it (see [references/application-model-oam.md](references/application-model-oam.md)).

**Cluster topology — hub-and-spoke (default):** a **hub** cluster runs the platform control plane (ArgoCD, Backstage, GitLab, Keycloak, Kargo); **spoke** clusters (dev, prod) run workloads. EKS **Auto Mode** is the default cluster type so the platform team isn't managing nodes. Infrastructure metadata flows to clusters via the **GitOps Bridge** pattern. Details: [references/idp-architecture.md](references/idp-architecture.md).

## The Golden Paths

A golden path is a paved, opinionated route from intent to running software, with guardrails baked in. The platform ships these as Backstage templates. The four core paths:

1. **Provision an environment** — Backstage template → kro composes VPC + EKS Auto Mode cluster + add-ons + ArgoCD registration. Minutes, not days. → [references/infrastructure-abstraction.md](references/infrastructure-abstraction.md)
2. **Provision an AWS resource** — Backstage template → ACK manifest committed to Git → ArgoCD syncs → ACK provisions the AWS resource. → [references/infrastructure-abstraction.md](references/infrastructure-abstraction.md)
3. **Onboard an application** — Backstage template → kro `CICDPipeline` → Argo Workflows CI + ArgoCD CD. Developer contract: provide a `Dockerfile` + the platform's application manifest (a kro-rendered resource, or an OAM `Application` if you run the KubeVela abstraction); the platform does the rest. → [references/developer-portal-backstage.md](references/developer-portal-backstage.md), [references/gitops-delivery.md](references/gitops-delivery.md)
4. **Ship safely to production** — Argo Rollouts canary with gates in dev; Kargo promotes the validated artifact to prod (auto in dev, manual approval for prod). → [references/progressive-delivery.md](references/progressive-delivery.md)

**The developer contract** (what app teams provide vs. what the platform handles) is the design heart of every golden path — see [references/golden-paths.md](references/golden-paths.md).

### Guardrails — making the paved path the *safe* path

Self-service is only safe if the guardrails are built **into** the golden path, so they apply automatically and a developer cannot accidentally skip them:

- **Policy-as-code** — an admission policy engine (Kyverno or OPA Gatekeeper) automatically rejects unsafe workloads at deploy time. Examples: no privileged containers, images only from approved registries, required labels present.
- **Supply-chain security** — the platform's CI signs each image and produces an SBOM (a bill of materials of what is inside the image), and the cluster only admits **signed** images. This guarantees every running container actually came from your pipeline, not from somewhere untrusted.
- **Least-privilege IAM, Pod Security Admission, and ingress conventions** — encoded once in the platform's application abstraction (the kro composition or, on KubeVela, the OAM traits), so every app inherits them by default instead of each team getting them right by hand.

The platform team owns these controls; app teams get them for free. For the cluster-level depth behind each one, use `eks-best-practices` (its `security.md` and `security-supply-chain.md` references).

## Application Modeling — the developer-facing abstraction

The goal of this layer is one declarative file in which a developer requests "an app + a DynamoDB table + an IAM-scoped service account + ingress" and the platform renders everything underneath — never raw Deployments/Services/Ingresses by hand.

**Default — Backstage templates + kro.** A Backstage software template collects the parameters; a kro `ResourceGraphDefinition` (authored by the platform team) composes the workload and its dependencies into one custom resource. This keeps the platform on a single composition engine (the same kro used for environment and resource provisioning).

**Alternative — OAM / KubeVela.** KubeVela implements the Open Application Model: developers describe apps with the OAM `Application` CRD, composed from platform-authored **Components** (a runnable unit, e.g. `appmod-service`, `dynamodb-table`) and **Traits** (an operational add-on, e.g. `path-based-ingress`, `component-iam-policy`) written in CUE, ordered with `dependsOn`. It is a richer application model and a fully supported choice. Note its current project velocity before standardizing on it.

Both abstractions, the CUE authoring model, the `appmod-service` example, and how to choose between them: [references/application-model-oam.md](references/application-model-oam.md).

## Progressive Delivery and Promotion

The platform's `appmod-service` component defaults to an **Argo Rollouts canary**: 20% → 40% → 60% → 80% → 100%, with **quality gates** that auto-rollback on failure:
- **Functional gate** (at 20%) — smoke/correctness test.
- **Performance gate** (at 80%) — load/latency test (e.g. Artillery).
- **Metrics gate** — developer-defined Prometheus queries (e.g. avg response time > 3s → fail).

**Kargo** orchestrates multi-stage promotion: a Warehouse watches ECR for new images; the **dev** stage auto-promotes; the **prod** stage requires manual approval and promotes the *exact same artifact* validated in dev. All promotions are Git commits (auditable, reversible). Strategies (canary/blue-green/A-B), gate config, and the Kargo Warehouse/Stage/Freight model: [references/progressive-delivery.md](references/progressive-delivery.md).

## Measuring Platform Success

A platform you can't measure is a platform you can't justify. Track the four **DORA** metrics — deployment frequency, lead time for changes, change failure rate, recovery time — with **Apache DevLake** ingesting signals from Argo Workflows/Rollouts and GitLab, visualized in Grafana. Measurement is zero-overhead: it's wired in when a team onboards via Backstage.

Pair delivery metrics with **cost visibility (showback):** attribute spend per team/tenant and surface it in the portal so each team sees what its workloads cost. DORA tells you how *fast* you ship; showback tells you what it *costs* to run. Cluster-level cost levers (Spot, Graviton, right-sizing, Karpenter consolidation) live in `eks-best-practices` (`cost-optimization.md`).

Framework and dashboards: [references/measuring-success.md](references/measuring-success.md).

## GenAI-Assisted Platform Engineering

GenAI accelerates both tracks: **code generation** (app developers) and **platform generation** (platform engineers — Backstage templates, kro/OAM compositions, deployment manifests). The reliable pattern is *reference example + target schema + prompt → generated artifact → human review*. Always human-in-the-loop; expect hallucinations.

**Use Kiro**, AWS's spec-driven agentic development tool and the **official successor to Amazon Q Developer** (Q Developer IDE plugins and paid subscriptions reach end of support on **April 30, 2027**; new sign-ups closed May 15, 2026). Kiro's spec-driven workflow (structured requirements → design → tasks), steering files for persistent project context, hooks, and custom subagents map directly onto platform-template generation. Spec/steering workflow, prompt patterns, and the migration note from Q Developer → [references/genai-platform-engineering.md](references/genai-platform-engineering.md).

## Identity and Multi-Tenancy

Keycloak provides SSO across all tools; for workload AWS access, **EKS Pod Identity is the recommended approach for new workloads** while **IRSA remains a fully supported alternative** (and the right choice on Fargate, Windows nodes, or where you already run OIDC federation); per-team namespaces, RBAC, and one-repo-per-component keep tenants isolated. Details: [references/identity-and-tenancy.md](references/identity-and-tenancy.md).

## Platform for AI/ML and Data Engineering

The same golden-path model extends to ML and data teams via Backstage templates:
- **Model development** — JupyterHub (multi-user notebooks, Keycloak SSO).
- **Model serving** — Ray Serve (Backstage template → Git → ArgoCD → Ray cluster → inference endpoint).
- **Data engineering** — the Kubeflow Spark Operator (`kubeflow/spark-operator`) (Backstage template → Argo Workflows → `SparkApplication` CRD).
- **Key pattern** — a DaemonSet pre-pulls large ML images to nodes to kill cold-start latency (on EKS Auto Mode, where nodes are managed and can recycle, pair this with a warm pool / node-lifecycle-aware approach — see reference).

Full ML/data golden paths: [references/aiml-data-platform.md](references/aiml-data-platform.md).

## How to Use the References

This skill uses **progressive disclosure** — the essentials are above; load a reference only when the task needs that depth:

| Reference | Load when the task is about… |
|-----------|------------------------------|
| [idp-architecture.md](references/idp-architecture.md) | IDP concept, reference architecture, hub-and-spoke, GitOps Bridge, value/challenges |
| [developer-portal-backstage.md](references/developer-portal-backstage.md) | Backstage portal, software templates/scaffolder, catalog, self-service flow |
| [gitops-delivery.md](references/gitops-delivery.md) | ArgoCD + Argo Workflows, app-of-apps, cluster registration, CI/CD wiring |
| [progressive-delivery.md](references/progressive-delivery.md) | Argo Rollouts strategies, quality gates, Kargo promotion |
| [infrastructure-abstraction.md](references/infrastructure-abstraction.md) | ACK and kro, self-service environment/resource provisioning |
| [application-model-oam.md](references/application-model-oam.md) | The developer-facing app model — Backstage+kro (default) vs OAM/KubeVela (alternative), components, traits, CUE |
| [golden-paths.md](references/golden-paths.md) | Golden-path design, guardrails, the developer contract, onboarding |
| [identity-and-tenancy.md](references/identity-and-tenancy.md) | Keycloak SSO, Pod Identity/IRSA, multi-tenant isolation |
| [measuring-success.md](references/measuring-success.md) | DORA metrics, Apache DevLake, platform dashboards |
| [genai-platform-engineering.md](references/genai-platform-engineering.md) | Kiro (successor to Amazon Q Developer) for templates/manifests, spec/steering workflow, prompt patterns |
| [aiml-data-platform.md](references/aiml-data-platform.md) | JupyterHub, Ray Serve, Kubeflow Spark Operator golden paths |

## Sources

- [Platform Engineering on EKS workshop (PEEKS)](https://github.com/aws-samples/platform-engineering-on-eks) and its companion [appmod-blueprints](https://github.com/aws-samples/appmod-blueprints)
- [Internal Developer Platform](https://internaldeveloperplatform.org/) · [CNCF Platforms White Paper](https://tag-app-delivery.cncf.io/whitepapers/platforms/)
- [Backstage](https://backstage.io/) · [Argo Project](https://argoproj.github.io/) (CD, Workflows, Rollouts) · [Kargo](https://kargo.io/)
- [AWS Controllers for Kubernetes (ACK)](https://aws-controllers-k8s.github.io/community/) · [kro](https://kro.run/) · [KubeVela / OAM](https://kubevela.io/) · [Kubeflow Spark Operator](https://github.com/kubeflow/spark-operator)
- [Amazon EKS Auto Mode](https://docs.aws.amazon.com/eks/latest/userguide/automode.html) · [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html) · [Kiro](https://kiro.dev/) · [Amazon Q Developer end-of-support notice](https://aws.amazon.com/blogs/devops/amazon-q-developer-end-of-support-announcement/) · [Apache DevLake (DORA)](https://devlake.apache.org/)
