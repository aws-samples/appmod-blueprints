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
