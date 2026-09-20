# IDP Architecture

The reference architecture for an Internal Developer Platform on EKS, and the framework for reasoning about IDP value and adoption.

## What an IDP is (and isn't)

An IDP is **not** a single product — it's an integrated collection of capabilities presented to platform users (developers, ML engineers, data engineers) so they can self-serve. CNCF: "an integrated collection of capabilities defined and presented according to the needs of the platform's users."

Analogy: a train-station platform. The platform adds value only when people actively use it. An IDP centralizes tools, services, and automation so app teams focus on their work, not infrastructure.

## The four goals of a platform team

1. Help developers work independently (self-service).
2. Reduce cognitive load.
3. Create reusable best practices ("golden paths").
4. Automate common tasks (clusters, CI/CD, resource provisioning).

## Value

| Benefit | What it means |
|---------|---------------|
| Speed | Get apps to customers faster |
| Control | Safe, consistent, secure operations |
| Cost | Economies of scale — adding the Nth app is cheap |
| Continuous improvement | Learnings shared across the org via golden paths |

## Challenges (and the counter-move)

| Challenge | Counter-move |
|-----------|--------------|
| Adoption — convincing devs to use it | Make the golden path the *easiest* path; understand real user needs |
| Right level of abstraction | Hide complexity but keep escape hatches; iterate |
| Organizational resistance | Treat the platform as a product; measure and show value (DORA) |
| Troubleshooting | Give devs visibility (portal surfaces logs/status) |

## Reference architecture (opinionated)

```
                         ┌──────────────────────────────────────────┐
   Developer ──▶ Backstage (portal, templates) ── Keycloak SSO ──────┤
                         │                                            │
                         ▼  git commit                                │
                      GitLab  ──webhook──▶ Argo Workflows (CI) ──▶ ECR │
                         │                                            │
                         ▼                                            │
                      ArgoCD (GitOps CD) ───────────────────────────▶ ┘
                         │  reconciles
        ┌────────────────┼─────────────────────────────────────┐
        ▼                ▼                                       ▼
   HUB cluster      SPOKE: dev                              SPOKE: prod
   (control plane)  (EKS Auto Mode)                         (EKS Auto Mode)
   ArgoCD/Backstage  Argo Rollouts (canary+gates)           Argo Rollouts
   GitLab/Keycloak   ACK · kro · KubeVela                   ACK · kro · KubeVela
   Kargo · DevLake   External Secrets                       External Secrets
        │  Kargo promotes validated artifact: dev ─────────────▶ prod
        └─────────────────────────────────────────────────────────┘
```

## Hub-and-spoke topology

- **Hub cluster** — runs the platform control plane: ArgoCD, Backstage, GitLab, Keycloak, Kargo, DevLake, Grafana. It is the management plane, not a workload plane.
- **Spoke clusters** — dev and prod, run application/ML/data workloads. Each spoke registers with the hub's ArgoCD and receives platform add-ons automatically.
- **Why hub-and-spoke:** centralizes control-plane operations, isolates workloads, and lets new spokes self-register and inherit the full add-on set via GitOps.
- **EKS Auto Mode** is the default cluster type for both hub and spokes so the platform team does not manage nodes, scaling, or patching.

> **Git provider is interchangeable.** This reference uses **GitLab** as the source + base-CI system because that is what the underlying workshop deploys, but nothing in the architecture depends on it. **GitHub** (with GitHub Actions or Argo Workflows), or any Git provider with webhooks, works identically — the platform contract is "a Git repo that triggers CI and that ArgoCD reconciles from." Swap the provider without changing the GitOps, promotion, or golden-path design.

## The GitOps Bridge pattern

The "GitOps Bridge" passes infrastructure metadata (cluster name, region, IAM role ARNs, VPC IDs, OIDC provider, add-on config) from the IaC/provisioning layer into the cluster as Kubernetes secrets/labels that ArgoCD ApplicationSets read. This decouples "how the cluster was built" from "what gets deployed onto it" — the same GitOps definitions target any registered cluster because the bridge supplies the per-cluster specifics.

Practically:
1. Provisioning (CDK/Terraform/kro) creates the cluster + a standardized cluster-registration secret containing metadata.
2. ArgoCD ApplicationSets template add-ons/apps using values from that secret.
3. New clusters become deployment targets the moment their registration secret exists.

## Component map (what each tool owns)

| Concern | Tool |
|---------|------|
| Front door / catalog / templates | Backstage |
| Identity / SSO | Keycloak |
| Source + base CI | GitLab (or GitHub / any webhook-capable Git provider) |
| GitOps reconciliation | ArgoCD |
| CI orchestration | Argo Workflows + Argo Events |
| Progressive delivery | Argo Rollouts |
| Multi-stage promotion | Kargo |
| AWS resources as CRDs | ACK |
| Resource composition (custom CRDs) | kro |
| App abstraction | Backstage templates + kro (default); KubeVela / OAM (alternative) |
| Secrets sync | External Secrets Operator |
| Workload IAM | EKS Pod Identity (recommended for new workloads) / IRSA |
| Metrics / dashboards / DORA | Prometheus, Grafana, Apache DevLake |
| GenAI assistance | Kiro (successor to Amazon Q Developer) |

See the matching references for each layer's depth.
