# Platform Engineering on EKS — appmod-blueprints

## Project Identity

Platform implementation repo for the Platform Engineering on EKS workshop. Provides GitOps configurations, Terraform infrastructure, Backstage templates, and sample applications for a multi-cluster EKS platform.

Companion repo: [platform-engineering-on-eks](../platform-engineering-on-eks/) handles CDK bootstrap and workshop content.

## Repository Layout

| Path | Purpose |
|------|---------|
| `platform/infra/terraform/cluster/` | Terraform — EKS clusters (hub, spoke-dev, spoke-prod) |
| `platform/infra/terraform/common/` | Terraform — platform addons (ArgoCD, secrets, pod identity, observability) |
| `platform/infra/terraform/identity-center/` | Terraform — IDC/SCIM integration |
| `platform/infra/terraform/scripts/` | Init scripts (`0-init.sh`, `argocd-utils.sh`, IDC config) |
| `platform/infra/terraform/hub-config.yaml` | Single source of truth for cluster addon enablement |
| `gitops/addons/` | ArgoCD addon definitions, charts, environments, tenants |
| `gitops/apps/` | Application deployment manifests (backend, frontend, rollouts) |
| `gitops/fleet/` | Fleet management (Kro values, bootstrap, members) |
| `gitops/platform/` | Platform bootstrap, charts, team configs |
| `gitops/workloads/` | Workload definitions (Ray, etc.) |
| `applications/` | Sample apps (Rust, Java, Go, .NET, Next.js) |
| `backstage/` | Backstage IDP (Dockerfile, config, plugins) |
| `platform/backstage/templates/` | Backstage software templates |
| `platform/validation/` | Cluster and Kro validation scripts |
| `hack/` | IDE environment config (.kiro, .zshrc, .bashrc.d, k9s) |
| `docs/` | Architecture docs, troubleshooting, feature guides |
| `scripts/` | Utility scripts (validation, keycloak) |

## Tech Stack

- **IaC:** Terraform (cluster, common, identity-center modules)
- **GitOps:** ArgoCD ApplicationSets with sync waves (-5 to 6)
- **Kubernetes:** EKS Auto Mode + EKS Capabilities (ArgoCD, Kro, ACK)
- **IDP:** Backstage with Keycloak SSO
- **Progressive delivery:** Argo Rollouts, Kargo
- **Observability:** CloudWatch, Grafana, DevLake (DORA metrics)
- **Task runner:** Taskfile (`Taskfile.yml`)
- **CI:** GitHub Actions (`.github/workflows/`)

## Key Conventions

- Resource prefix: `peeks` (flows from env var through Terraform to cluster secrets)
- Cluster names: `peeks-hub`, `peeks-spoke-dev`, `peeks-spoke-prod`
- Deployment scripts: always use `deploy.sh` / `destroy.sh`, never raw `terraform apply/destroy`
- Addon enablement: `hub-config.yaml` → Terraform → cluster secret labels → ArgoCD ApplicationSets
- Dynamic values (resource_prefix, domain, region) live in `addons.yaml` valuesObject only, never in `values.yaml`

## Two Usage Contexts

This repo is used in two ways:

1. **Local development** (you, on macOS) — edit Terraform, GitOps configs, scripts, then push to GitHub
2. **Workshop IDE** (ec2-user, on the Code Editor instance) — workshop participants interact with the deployed platform. The `hack/` directory configures this environment, including `hack/.kiro/` for the IDE's Kiro agent.

The root `.kiro/` is for local dev. `hack/.kiro/` is for the workshop IDE — they serve different audiences.


## Working Agreement (how to operate in this repo)

Binding behavioral expectations, learned from working sessions. Follow these.

### Verify, do not speculate
- Replace guesses and "I think / it should" with **actual evidence**: command output, test results, rendered manifests, file contents, live cluster state.
- Before claiming a cause or a fix works, prove it (e.g. `helm template`, `kubectl get`, read the file, check the live resource).
- If something cannot be verified, say so plainly. An honest "I haven't verified X / I don't know" is required over a confident-sounding guess.
- When stating a root cause, cite the specific evidence that establishes it.

### Do not waste time
- **Never use `sleep` to wait for reconciliation.** Trigger the action (sync/patch/refresh) and check status directly. If a result isn't ready, re-check on the next action — do not block on timers.
- Don't poll in loops. Take the direct action.

### Don't go in circles — find the root cause
- If an approach fails twice, stop repeating variations. Step back and diagnose the underlying cause with evidence, then fix that.
- Trace problems to their source (e.g. which repo/branch/cache actually serves a value) rather than patching symptoms.

### Solutions live in git
- Fixes must be committed to git and applied via GitOps. **Do not use `kubectl patch`/`edit`/`apply` as a fix.**
- `kubectl` is for diagnosis and for triggering ArgoCD syncs/refreshes only — never for mutating desired state as the solution.

### Question necessity; remove redundancy
- Before adding code, check whether it is actually needed (e.g. RBAC may already be granted by an existing ClusterRole).
- Prefer **removing** redundant or workaround code over gating it behind flags. If a change isn't needed, drop it.

### One consistent model, no per-case workarounds
- Apply a single uniform pattern across the board rather than special-casing individual workloads.
- If a workaround was introduced under pressure, revisit and replace it with the consistent approach.

### Professional, customer-neutral output
- No workshop/demo artifacts leaking into the solution (e.g. avoid `tenant: workshop`; use neutral defaults like `default`).
- **Do not force platform conventions onto customers.** Cluster names are customer-supplied and arbitrary — never derive or enforce them from `resourcePrefix`. The prefix exists only to scope account/region-global AWS resource names (IAM roles, AMP/AMG workspaces, security groups, ECR) to avoid collisions across installs.


## Operational Invariants (binding — do not re-investigate)

These are facts about the deployed platform that have been confirmed multiple times. Treat as ground truth and avoid re-asking the user about them.

### ArgoCD on the hub is the EKS managed ArgoCD Capability

- ArgoCD on `peeks-hub` is **provisioned as an EKS managed Capability**, not as Helm-installed pods in the cluster.
- The control-plane components (`argo-cd-argocd-server`, `argo-cd-argocd-application-controller`, `argo-cd-argocd-repo-server`, etc.) **run inside the AWS-managed control plane** and are **not visible** via `kubectl get pods -n argocd`. That namespace looks empty for pods even when ArgoCD is fully operational.
- What IS visible in the `argocd` namespace: `Application`, `ApplicationSet`, `AppProject`, and cluster `Secret` objects — these are user-facing CRDs that ArgoCD reconciles from outside.
- "ArgoCD is broken because the namespace is empty" is **always wrong**. Verify ArgoCD health by checking that `Application` resources are reconciling (sync/health status) rather than by looking for pods.
- Self-managed ArgoCD values files (e.g. anything under `gitops/addons/configs/argo-cd/values.yaml` or `platform/infra/terraform/common/manifests/argocd-initial-values.yaml`) are **dead code** from a prior install path and have been removed. The Capability does not consume them.
- Capability configuration lives in `platform/infra/terraform/common/argocd.tf` and the EKS cluster module — not in Helm values files.

### Multi-cluster register pattern

- Cluster secrets in the hub's `argocd` namespace use **EKS ARNs** as the cluster `server` value, not `kubernetes.default.svc`.
- Duplicate cluster secrets with the same ARN are rejected by ArgoCD.
- Spokes (`spoke-dev`, `spoke-prod`) run their own workloads but **do not run ArgoCD**. The hub's ArgoCD reconciles into them via the registered cluster secrets.

### Pod Identity, not IRSA

- The platform uses EKS Pod Identity (not IRSA) for pod-level AWS credentials on EKS Auto Mode.
- When provisioning IAM access for a workload, use `aws eks create-pod-identity-association` (not OIDC trust policies).
