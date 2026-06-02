# Platform Engineering on EKS — feature/cloudfront-exposure

## Context

This is the `appmod-blueprints` repository on branch `feature/cloudfront-exposure`. It implements a GitOps-based platform engineering stack on EKS using Kind+Crossplane bootstrap, ArgoCD ApplicationSets, and EKS Capabilities.

## Environment

- User: `ec2-user`
- Repo: `/home/ec2-user/environment/appmod-blueprints`
- Branch: `feature/cloudfront-exposure`
- Config: `config.local.yaml` (clusterProvider: kind-crossplane, exposure: cloudfront)
- Hub cluster: `peeks-hub`
- Spoke clusters: `spoke-dev`, `spoke-prod` (provisioned by Crossplane on hub)
- CloudFront domain: stored in `private/cloudfront-domain`

## Key Architecture Decisions

- **EKS Auto Mode** — no Karpenter, no OSS LBC; built-in ALB via IngressClassParams
- **EKS Capabilities** — ArgoCD, KRO, ACK run as managed services (not pods)
- **Exposure mode: cloudfront** — single ALB behind CloudFront, no custom domain needed
- **ALB URL rewrite** — uses `alb.ingress.kubernetes.io/transforms.<svc>` annotation (LBC v2.14.0+)
- **IDC ↔ Keycloak SCIM** — Keycloak is external IdP for IDC; users synced via SCIM

## Bootstrap Flow (task install)

```
Kind cluster → Crossplane provisions VPC+EKS → ArgoCD Capability created (+ KRO + ACK)
→ ESO installed on hub → ClusterSecretStore → Seed secret → Root AppSet applied
→ Hub self-manages → Addons deploy → Observability seeded → IDC configured
```

## Cluster Provisioning (two paths)

| Path | Mechanism | Use Case |
|------|-----------|----------|
| `abstractions/crossplane/platform-cluster/` | Crossplane XRD + Composition | Platform team creates spokes (values in `fleet/kro-values/tenants/`) |
| `abstractions/kro/kro-clusters/` | KRO cluster provisioning chart | Platform team creates spokes via KRO (values in `fleet/kro-values/tenants/*/kro-clusters-kro/`) |
| `addons/charts/kro/resource-groups/manifests/eks/` | KRO ResourceGraphDefinition + ACK | Self-service via Backstage templates |

Both coexist. Crossplane path creates `PlatformCluster` claims. KRO path creates `EksCluster` custom resources reconciled by ACK.

## Repository Layout

| Path | Purpose |
|------|---------|
| `config.local.yaml` | Local deployment config (provider, IDC, exposure mode) |
| `Taskfile.yaml` | Root orchestrator — delegates to cluster provider |
| `cluster-providers/kind-crossplane/` | Bootstrap via Kind + Crossplane |
| `cluster-providers/terraform/` | Bootstrap via Terraform (alternative) |
| `gitops/bootstrap/` | Root AppSet, cluster-addons, fleet-secrets |
| `gitops/addons/registry/` | Addon definitions by domain (core, platform, security...) |
| `gitops/addons/configs/` | Per-addon Helm values |
| `gitops/addons/charts/` | Custom wrapper charts (backstage, keycloak, argo-workflows...) |
| `gitops/overlays/environments/` | Per-environment addon enablement + overrides |
| `gitops/overlays/clusters/` | Per-cluster overrides |
| `gitops/fleet/members/` | Fleet member registration |
| `gitops/fleet/kro-values/` | Cluster provisioning values (Crossplane path) |
| `gitops/abstractions/crossplane/` | Crossplane compositions (platform-cluster, aws-resources) |
| `platform/backstage/templates/` | Backstage software templates |
| `platform/infra/terraform/scripts/` | IDC configuration, ArgoCD token automation |
| `scripts/` | Utility scripts (keycloak-idc-credentials.sh) |

## Key Rules

- **Use `task install`** — never raw terraform or manual kubectl for bootstrap
- **GitOps first** — modify Git, let ArgoCD sync; don't kubectl apply manually
- **CloudFront exposure** — all apps share one ALB+CloudFront; path-based routing with URL rewrite
- **No domain required** — `domain: ""` in config; CloudFront provides HTTPS
- **Check env vars with echo** — don't dump full environment
- **ArgoCD CLI auth** — run `argocd-refresh-token` then `source ~/.bashrc.d/platform.sh`

## App URLs (cloudfront mode)

| App | Path | Notes |
|-----|------|-------|
| Backstage | `/backstage` | Uses transforms annotation for rewrite |
| Keycloak | `/keycloak` | Serves natively at this path |
| Argo Workflows | `/argo-workflows` | Uses transforms annotation for rewrite |

## Authentication

- **ArgoCD Capability** — users authenticate via IDC SSO (Keycloak is external IdP for IDC)
- **Platform apps** (Backstage, Argo Workflows) — authenticate via Keycloak OIDC
- **Keycloak users** — synced to IDC via SCIM (configure_identity_center.py)
- **Passwords** — stored in Secrets Manager (`peeks-hub/keycloak` → `user_password`)

## Credentials

| Service | Username | Password Source |
|---------|----------|----------------|
| Keycloak admin | `admin` | `peeks-hub/keycloak` → `keycloak_admin_password` |
| Platform user | `user1` | `peeks-hub/keycloak` → `user_password` |
| ArgoCD | via IDC SSO | user1 logs in through IDC (federated to Keycloak) |
