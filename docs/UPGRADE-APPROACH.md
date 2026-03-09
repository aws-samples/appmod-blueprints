# Appmod Blueprints: Solution Upgrade Approach

## Executive Summary

This document outlines the detailed approach to transform the `appmod-blueprints` repository from a workshop-coupled monolith into a modular, externally consumable platform engineering accelerator. The goal is to enable customers and partners to adopt this solution in their own repositories (e.g., their GitHub/GitLab repos) **without forking**, while preserving the workshop experience as one pattern of usage.

The platform follows a **GitOps-native, self-managing architecture**: the hub cluster manages itself and all platform components using Kro+ACK or CrossPlane compositions — **no Terraform in the solution repo**. Terraform (or eksctl, CDK, CLI) is only used for the initial EKS cluster creation, which lives outside `appmod-blueprints` (e.g., in the customer's own infra repo or the workshop repo).

This work is also foundational for expanding the solution into an **Agent Platform on EKS**.

---

## 1. Current State Analysis

### 1.1 Repository Structure (As-Is)

```
appmod-blueprints/
├── applications/              # Sample apps (Java, Node, Python, Go, .NET, Rust, Next.js)
├── backstage/                 # Backstage IDP (full app: frontend + backend + Kro plugin)
├── gitops/
│   ├── addons/                # ArgoCD addon charts (27+ charts)
│   │   ├── bootstrap/         # Default addon values
│   │   ├── charts/            # Helm charts (keycloak, backstage, gitlab, kro, ray, etc.)
│   │   ├── environments/      # Per-environment overrides
│   │   └── tenants/           # Per-tenant overrides
│   ├── apps/                  # Application deployment manifests
│   ├── fleet/                 # Multi-cluster management (ApplicationSets, Kro values)
│   ├── platform/              # Platform team resources
│   └── workloads/             # ML/AI workloads (Ray, Spark)
├── platform/
│   ├── backstage/             # Backstage templates for self-service
│   ├── infra/terraform/       # All Terraform code
│   │   ├── cluster/           # EKS cluster creation (hub + spokes)
│   │   ├── common/            # Platform bootstrap (ArgoCD, GitLab, secrets, IAM, CloudFront, etc.)
│   │   ├── database/          # RDS/Aurora resources
│   │   ├── identity-center/   # AWS Identity Center
│   │   ├── scripts/           # Deployment automation (0-init.sh, utils.sh, etc.)
│   │   └── hub-config.yaml    # Central configuration file
│   └── validation/            # Validation scripts
├── scripts/                   # Utility scripts
└── hack/                      # Development helpers
```

### 1.2 Key Coupling Issues Identified

| Coupling Point | Description | Impact |
|---|---|---|
| `hub-config.yaml` is embedded in repo | Central config lives inside the solution repo, not externally | Customers must fork to customize |
| Terraform is not modular | `cluster/` and `common/` are standalone stacks, not reusable modules | Cannot `source` from GitHub with a tag |
| GitLab is deeply embedded | `argocd.tf` creates GitLab PATs, `locals.tf` hardcodes GitLab repo URLs, `gitlab.tf` manages tokens | Cannot swap Git provider without code changes |
| Keycloak-Backstage-GitLab triad | Backstage depends on Keycloak for auth, GitLab for templates; all share `USER1_PASSWORD` | Cannot deploy Backstage without both Keycloak and GitLab |
| Workshop-specific code in solution | `WORKSHOP_CLUSTERS` flag in `utils.sh`, `workshop_participant_role_arn` in cluster vars, `ide_password` variable | Workshop concerns pollute the solution |
| CloudFront hardcoded for ingress | `cloudfront.tf` creates a distribution tightly coupled to the NLB | Customers with their own DNS/ingress cannot reuse |
| Secrets assume workshop topology | `secrets.tf` creates per-cluster secrets with GitLab tokens, user passwords | Assumes specific identity provider and Git provider |
| Repo URLs hardcoded in locals | `locals.tf` constructs repo URLs assuming GitLab: `"https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git"` | Cannot point to GitHub or other Git providers |
| `deploy.sh` scripts embed logic | Each stack has `deploy.sh` with env var setup, backend config, workshop-specific logic | Not consumable as standard Terraform modules |
| Backstage image hardcoded | `backstage_image` defaults to `public.ecr.aws/seb-demo/backstage:latest` | Customers need their own Backstage build |

### 1.3 Current Terraform Split

The Terraform code is already split into two phases:

1. **Phase 1 - Cluster Stack** (`platform/infra/terraform/cluster/`): Creates EKS clusters (hub + spokes) with VPC, node groups, and EKS Auto Mode. Can theoretically run on existing clusters but is not documented or tested for that path.

2. **Phase 2 - Common/Bootstrap Stack** (`platform/infra/terraform/common/`): Deploys platform addons — ArgoCD bootstrap, GitLab infra, CloudFront, IAM roles, Pod Identity, secrets, ingress, observability. This is the most coupled stack.

---

## 2. Target Architecture (To-Be)

### 2.1 Design Principles

1. **GitOps-native self-management**: The hub cluster manages itself and all platform components using Kro+ACK or CrossPlane compositions. No Terraform in the solution repo. Initial EKS cluster creation (via Terraform, eksctl, CDK, or CLI) is the customer's responsibility and lives outside `appmod-blueprints`.
2. **Config-external**: `hub-config.yaml` lives outside the repo; customers pass their own config. The config drives Kro/CrossPlane compositions and ArgoCD bootstrap.
3. **Provider-agnostic**: Git provider (GitHub vs GitLab), OIDC provider, and CI/CD provider are swappable via configuration
4. **GitOpsy spokes**: Spoke clusters provisioned and managed via CrossPlane/Kro through the hub cluster — same mechanism as hub self-management
5. **Workshop as a pattern**: Workshop-specific code (including Terraform for cluster creation) moves to the internal `platform-engineering-on-eks` GitLab repo, keeping `appmod-blueprints` clean as the customer-facing solution
6. **Composable components**: Keycloak, Backstage, GitLab are independently deployable addons
7. **Practice what we preach**: Use the platform (EKS + ArgoCD) to deploy all components/connections/software wherever possible, rather than relying on Terraform for things external to the base platform

### 2.2 Target Repository Structure

```
appmod-blueprints/
├── compositions/                     # NEW: Kro RGDs and CrossPlane compositions
│   ├── hub-bootstrap/                #   Hub self-management (ArgoCD, secrets, IAM via ACK)
│   ├── ingress/                      #   Ingress setup (CloudFront or custom via ACK)
│   ├── identity/                     #   Identity provider integration (Keycloak or external)
│   ├── observability/                #   Grafana, Prometheus, CloudWatch via ACK
│   ├── spoke-cluster/                #   Spoke cluster lifecycle (create, bootstrap, destroy)
│   └── secrets/                      #   AWS Secrets Manager via ACK/CrossPlane
├── examples/                         # NEW: Example configurations
│   ├── full-platform/                #   Full deployment (hub + spokes + all addons)
│   ├── hub-only/                     #   Hub cluster with minimal addons
│   ├── existing-cluster/             #   Bootstrap on existing EKS cluster
│   └── byog/                         #   Bring Your Own Git (GitHub, GitLab, CodeCommit)
├── applications/                     # UNCHANGED: Sample apps
├── backstage/                        # UNCHANGED: Backstage IDP
├── gitops/                           # REFACTORED: GitOps configurations
│   ├── addons/                       #   Platform addon charts (27+ charts)
│   ├── apps/                         #   Application deployments
│   ├── fleet/                        #   Multi-cluster management
│   ├── platform/                     #   Platform team resources
│   └── workloads/                    #   ML/AI workloads
├── platform/
│   ├── backstage/                    # UNCHANGED: Backstage templates
│   └── validation/                   # UNCHANGED
├── hub-config.yaml                   # MOVED: Default config (top-level, overridable)
└── docs/                             # UPDATED: Architecture + consumption guides
```

> **Key change**: The `platform/infra/terraform/` directory is removed from `appmod-blueprints`. All Terraform code (cluster creation, GitLab PATs, workshop-specific infra) moves to the `platform-engineering-on-eks` internal GitLab repo. The solution repo is purely GitOps-native.

---

## 3. Detailed Change Plan

### 3.1 Phase 1: Hub Self-Management via Kro+ACK/CrossPlane (Foundation)

**Goal**: Replace all Terraform-managed platform bootstrap with Kro ResourceGraphDefinitions (RGDs) and ACK/CrossPlane compositions so the hub cluster manages itself after initial creation.

**Rationale**: "Practice what we preach" — use the platform (EKS + ArgoCD) to deploy all components/connections/software rather than relying on Terraform for things external to the base platform. Customers only need to create an EKS cluster (via any tool) and point ArgoCD at `appmod-blueprints`. The platform bootstraps itself.

#### 3.1.1 Create `compositions/hub-bootstrap/`

Replace the functionality of `platform/infra/terraform/common/` with Kro RGDs and ACK resources deployed via ArgoCD:

| Current Terraform File | Replacement | Details |
|---|---|---|
| `argocd.tf` | ArgoCD bootstrap addon chart (already exists) | ArgoCD is already deployed via GitOps; remove TF dependency on GitLab PAT. Git credentials provided via External Secrets or Kubernetes Secret |
| `secrets.tf` | `compositions/secrets/` — ACK Secrets Manager controller | Kro RGD that creates AWS Secrets Manager secrets via ACK. Secrets are synced to K8s via External Secrets Operator |
| `iam.tf` | `compositions/hub-bootstrap/iam-rgd.yaml` — ACK IAM controller | Kro RGD that creates IAM roles and policies via ACK IAM controller. Pod Identity associations created as K8s resources |
| `pod-identity.tf` | Native K8s Pod Identity resources | Pod Identity associations are Kubernetes resources, deployed via ArgoCD addon charts |
| `cloudfront.tf` | `compositions/ingress/cloudfront-rgd.yaml` — ACK CloudFront controller | Kro RGD that creates CloudFront distribution via ACK. Optional — customers can skip |
| `ingress-nginx.tf` | Already a Helm chart in `gitops/addons/charts/` | Ingress NGINX is already deployed via ArgoCD |
| `observability.tf` | `compositions/observability/` — ACK Grafana + Prometheus controllers | Kro RGD that creates Amazon Managed Grafana and Prometheus via ACK |
| `gitlab.tf` | Moves to `platform-engineering-on-eks` repo | Workshop-specific, not part of the solution |
| `model-storage.tf` | `compositions/hub-bootstrap/model-storage-rgd.yaml` — ACK S3 controller | Kro RGD for ML model storage S3 bucket |
| `ray-image-build.tf` | `compositions/hub-bootstrap/ray-image-rgd.yaml` — ACK CodeBuild controller | Kro RGD for Ray image build pipeline |

**Key architecture**:
```
Customer creates EKS cluster (any tool: eksctl, CDK, TF, CLI)
     │
     ▼
Install ArgoCD on the cluster (helm install or EKS addon)
     │
     ▼
Point ArgoCD at appmod-blueprints repo with hub-config.yaml
     │
     ▼
ArgoCD deploys bootstrap addons:
  ├── ACK controllers (IAM, S3, SecretsManager, CloudFront, etc.)
  ├── CrossPlane / Kro
  ├── External Secrets Operator
  └── Platform addon charts
     │
     ▼
Kro RGDs / CrossPlane compositions self-manage:
  ├── IAM roles and policies (via ACK IAM)
  ├── Secrets Manager secrets (via ACK SecretsManager)
  ├── CloudFront distribution (via ACK CloudFront, optional)
  ├── Managed Grafana + Prometheus (via ACK, optional)
  ├── Pod Identity associations (native K8s)
  └── Spoke clusters (via ACK EKS / CrossPlane)
     │
     ▼
Platform is fully self-managing via GitOps
```

#### 3.1.2 Create `compositions/secrets/`

Replace `platform/infra/terraform/common/secrets.tf`:

- Kro RGD that creates AWS Secrets Manager secrets via ACK SecretsManager controller
- Secrets structure is provider-agnostic: accepts `git_config`, `identity_config` from `hub-config.yaml`
- External Secrets Operator syncs AWS secrets to Kubernetes secrets
- No hardcoded GitLab tokens or Keycloak passwords — all driven by config

#### 3.1.3 Create `compositions/ingress/`

Replace `platform/infra/terraform/common/cloudfront.tf`:

- Kro RGD that optionally creates CloudFront distribution via ACK CloudFront controller
- Conditional on `ingress.type` in `hub-config.yaml`
- Supports: `cloudfront` (ACK), `alb` (ALB Ingress Controller), `nlb`, `custom` (customer-managed)
- Ingress NGINX remains as an ArgoCD addon chart (already GitOps-native)

#### 3.1.4 Create `compositions/observability/`

Replace `platform/infra/terraform/common/observability.tf`:

- Kro RGD that creates Amazon Managed Grafana workspace via ACK
- Kro RGD that creates Amazon Managed Prometheus workspace via ACK
- Optional — controlled by `enable_grafana` and `enable_prometheus` in hub-config addons

#### 3.1.5 Move Terraform to `platform-engineering-on-eks` Repo

All Terraform code moves out of `appmod-blueprints`:

| Current Location | Destination | Reason |
|---|---|---|
| `platform/infra/terraform/cluster/` | `platform-engineering-on-eks/terraform/cluster/` | Cluster creation is outside the solution — it's the customer's (or workshop's) responsibility |
| `platform/infra/terraform/common/` | Replaced by `compositions/` in `appmod-blueprints` | Platform bootstrap is now GitOps-native |
| `platform/infra/terraform/common/gitlab.tf` | `platform-engineering-on-eks/terraform/gitlab.tf` | Workshop-specific |
| `platform/infra/terraform/database/` | `platform-engineering-on-eks/terraform/database/` | Workshop-specific or replaced by ACK RDS controller |
| `platform/infra/terraform/identity-center/` | `platform-engineering-on-eks/terraform/identity-center/` | Workshop-specific |
| `platform/infra/terraform/scripts/` | `platform-engineering-on-eks/scripts/` | Deployment scripts are workshop-specific |
| `platform/infra/terraform/hub-config.yaml` | `hub-config.yaml` (top-level in `appmod-blueprints`) | Config stays but moves to repo root; becomes a default/example |

### 3.2 Phase 2: Externalize Hub Configuration

**Goal**: Allow customers to use `hub-config.yaml` externally. The config drives Kro/CrossPlane compositions and ArgoCD bootstrap — not Terraform.

#### 3.2.1 Changes to `hub-config.yaml`

Current location: `platform/infra/terraform/hub-config.yaml` (embedded in TF directory)

Target: Moves to repo root as `hub-config.yaml` (default/example). Customers provide their own externally. The config is consumed by ArgoCD bootstrap and Kro compositions as a ConfigMap or values file.

Add new top-level keys for provider configuration:
```yaml
# hub-config.yaml (customer's version)
domain_name: mycompany.com
resource_prefix: myplatform

git:
  provider: github                    # NEW: github | gitlab | codecommit
  url: https://github.com/myorg/myrepo
  revision: main
  basepath: gitops/fleet/

identity:
  provider: cognito                   # NEW: keycloak | cognito | okta | external
  config:
    user_pool_id: us-west-2_xxxxx

cicd:
  provider: github-actions            # NEW: argo-workflows | gitlab-ci | github-actions

ingress:
  type: alb                           # NEW: cloudfront | alb | nlb | custom
  domain: platform.mycompany.com
  certificate_arn: arn:aws:acm:...

clusters:
  hub:
    name: hub
    region: us-west-2
    kubernetes_version: "1.32"
    environment: control-plane
    tenant: control-plane
    auto_mode: true
    addons:
      enable_argocd: true
      enable_keycloak: false           # Customer uses Cognito instead
      enable_backstage: true
      enable_gitlab: false             # Customer uses GitHub instead
      # ...
```

#### 3.2.2 Hub Config as ConfigMap

The `hub-config.yaml` is loaded into the cluster as a ConfigMap that Kro compositions and ArgoCD addon charts consume:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: hub-config
  namespace: argocd
data:
  hub-config.yaml: |
    # Full hub-config.yaml content
```

This ConfigMap is created during the initial ArgoCD bootstrap (either manually or via a bootstrap script). Kro RGDs and addon charts reference it for provider-specific configuration.

#### 3.2.3 Remove `utils.sh` and `deploy.sh` from Solution Repo

Since Terraform is no longer in `appmod-blueprints`, the deployment scripts move entirely to `platform-engineering-on-eks`:

| Script | Action |
|---|---|
| `platform/infra/terraform/scripts/utils.sh` | Move to `platform-engineering-on-eks/scripts/utils.sh` |
| `platform/infra/terraform/cluster/deploy.sh` | Move to `platform-engineering-on-eks/scripts/deploy-cluster.sh` |
| `platform/infra/terraform/common/deploy.sh` | Replaced by ArgoCD bootstrap — no deploy script needed in solution repo |
| `platform/infra/terraform/scripts/2-gitlab-init.sh` | Move to `platform-engineering-on-eks/scripts/gitlab-init.sh` |
| `platform/infra/terraform/scripts/check-workshop-setup.sh` | Move to `platform-engineering-on-eks/scripts/check-setup.sh` |

The solution repo provides a lightweight bootstrap guide instead:
```bash
# Customer bootstrap flow (no Terraform in appmod-blueprints)
# 1. Create EKS cluster (any tool)
eksctl create cluster --name hub --region us-west-2

# 2. Install ArgoCD
helm install argocd argo/argo-cd -n argocd --create-namespace

# 3. Apply hub-config as ConfigMap
kubectl create configmap hub-config -n argocd --from-file=hub-config.yaml

# 4. Point ArgoCD at appmod-blueprints
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-bootstrap
  namespace: argocd
spec:
  source:
    repoURL: https://github.com/aws-samples/appmod-blueprints
    targetRevision: v1.0.0
    path: gitops/addons/charts/application-sets
  destination:
    server: https://kubernetes.default.svc
EOF

# 5. Platform self-manages from here
```

### 3.3 Phase 3: Decouple Keycloak-Backstage-GitLab

**Goal**: Make each component independently deployable and swappable.

#### 3.3.1 Decouple GitLab from ArgoCD Bootstrap

Current state in `argocd.tf`:
```hcl
# Git secrets depend on gitlab_personal_access_token.workshop
resource "kubernetes_secret" "git_secrets" {
  depends_on = [
    module.gitops_bridge_bootstrap,
    gitlab_personal_access_token.workshop  # <-- TIGHT COUPLING
  ]
```

Changes:
- Accept `git_credentials` as an input variable (token, username)
- Remove `gitlab_personal_access_token` dependency from `argocd.tf`
- Move GitLab provider configuration to `workshop/` or make it conditional

#### 3.3.2 Decouple Backstage from Keycloak

Current state: Backstage requires Keycloak for OIDC auth (sync waves 10→15→25).

Changes to `gitops/addons/charts/backstage/`:
- Add `auth.provider` value: `keycloak | cognito | github | guest`
- Template the OIDC configuration based on provider
- Make Keycloak dependency conditional in ArgoCD sync waves
- Support standalone Backstage with guest auth for development

#### 3.3.3 Decouple Backstage from GitLab

Current state: Backstage templates publish to GitLab repos, `app-config.yaml` has GitLab integration.

Changes:
- Add `git.provider` value to Backstage Helm chart
- Template Git integration in `app-config.yaml`:
  ```yaml
  integrations:
    {{- if eq .Values.git.provider "gitlab" }}
    gitlab:
      - token: ${GIT_PASSWORD}
        host: ${GIT_HOSTNAME}
    {{- else if eq .Values.git.provider "github" }}
    github:
      - host: github.com
        token: ${GITHUB_TOKEN}
    {{- end }}
  ```
- Update Backstage templates to support multiple Git providers in `publish` step

#### 3.3.4 Make Keycloak Optional

Current state: Keycloak is required for ArgoCD, Backstage, GitLab, Argo Workflows, Kargo auth.

Changes:
- Add `identity.provider` to hub-config
- When `enable_keycloak: false`, skip Keycloak deployment
- Support external OIDC provider configuration via External Secrets
- Update all dependent charts to accept generic OIDC config

### 3.4 Phase 4: Workshop Isolation

**Goal**: Move all workshop-specific code (including ALL Terraform) to the internal `platform-engineering-on-eks` GitLab repo. The `appmod-blueprints` repo becomes a clean, customer-facing, GitOps-native solution with zero Terraform and zero workshop concerns.

#### 3.4.1 Files to Move

| Current Location | Destination (platform-engineering-on-eks repo) | Reason |
|---|---|---|
| `platform/infra/terraform/` (entire directory) | `platform-engineering-on-eks/terraform/` | ALL Terraform is workshop/infra-specific — solution is GitOps-native |
| `platform/infra/terraform/common/gitlab.tf` | `platform-engineering-on-eks/terraform/gitlab.tf` | GitLab PAT creation is workshop-specific |
| `platform/infra/terraform/scripts/` (all scripts) | `platform-engineering-on-eks/scripts/` | Deployment scripts are workshop-specific |
| CloudFormation bootstrap references | `platform-engineering-on-eks/cloudformation/` | Workshop Studio setup |
| `backstage_image` default (`public.ecr.aws/seb-demo/backstage:latest`) | `platform-engineering-on-eks/config/` | Workshop-specific image |

#### 3.4.2 Workshop in `platform-engineering-on-eks` Repo

The internal `platform-engineering-on-eks` GitLab repo becomes the workshop-specific layer that creates the EKS cluster and then points ArgoCD at `appmod-blueprints` for self-management:

```
platform-engineering-on-eks/          # Internal GitLab repo (workshop)
├── hub-config.yaml                   # Workshop-specific config (GitLab, Keycloak, all addons)
├── deploy.sh                         # Orchestrates full workshop deployment
├── destroy.sh                        # Full cleanup
├── terraform/
│   ├── cluster/                      # EKS cluster creation (hub only; spokes via Kro/CrossPlane)
│   │   ├── main.tf                   # EKS module call
│   │   ├── variables.tf              # Cluster variables
│   │   └── outputs.tf                # Cluster outputs
│   ├── gitlab.tf                     # GitLab PAT and project creation
│   ├── workshop-overrides.tf         # Workshop-specific TF resources
│   └── variables.tf                  # Workshop-specific variables
├── scripts/
│   ├── utils.sh                      # Workshop-specific utilities
│   ├── gitlab-init.sh                # GitLab repo initialization
│   ├── bootstrap-argocd.sh           # Install ArgoCD + apply hub-config ConfigMap
│   └── check-setup.sh               # Workshop validation
├── content/                          # Workshop content and instructions
└── README.md                         # Workshop deployment guide
```

The workshop deployment flow:
```bash
# platform-engineering-on-eks/deploy.sh
# 1. Create EKS hub cluster via Terraform
cd terraform/cluster && terraform apply

# 2. Install ArgoCD on the hub
./scripts/bootstrap-argocd.sh

# 3. Apply workshop hub-config as ConfigMap
kubectl create configmap hub-config -n argocd --from-file=hub-config.yaml

# 4. Point ArgoCD at appmod-blueprints — platform self-manages from here
kubectl apply -f bootstrap-application.yaml

# 5. Run workshop-specific setup (GitLab init, etc.)
./scripts/gitlab-init.sh
```

### 3.5 Phase 5: GitOps for All Clusters (Hub Self-Management + Spoke Provisioning)

**Goal**: The hub cluster manages itself and provisions spoke clusters entirely via GitOps (Kro+ACK/CrossPlane). No Terraform involvement after initial cluster creation.

#### 3.5.1 Current State

- Hub cluster is created and bootstrapped by Terraform (`cluster/` + `common/` stacks)
- Spoke clusters are created by Terraform alongside the hub
- All AWS resources (IAM, Secrets, CloudFront, etc.) are Terraform-managed

#### 3.5.2 Target State

- Hub cluster creation is done once by any tool (eksctl, CDK, TF, CLI) — this is outside `appmod-blueprints`
- After ArgoCD is installed and pointed at `appmod-blueprints`, the hub self-manages:
  - IAM roles/policies via ACK IAM controller
  - Secrets via ACK SecretsManager + External Secrets Operator
  - CloudFront via ACK CloudFront controller (optional)
  - Observability via ACK Grafana/Prometheus (optional)
  - Pod Identity via native K8s resources
- Spoke clusters are provisioned exclusively via Kro RGDs or CrossPlane compositions from the hub
- ArgoCD ApplicationSets auto-discover and bootstrap new spokes
- Backstage templates allow self-service spoke creation

#### 3.5.3 Changes Required

| Component | Change |
|---|---|
| `compositions/hub-bootstrap/` | NEW: Kro RGDs for IAM, secrets, pod identity — replaces `platform/infra/terraform/common/` |
| `compositions/spoke-cluster/` | NEW: Kro RGD for spoke cluster lifecycle (create via ACK EKS, bootstrap, destroy) |
| `compositions/ingress/` | NEW: Kro RGD for CloudFront via ACK (optional) |
| `compositions/observability/` | NEW: Kro RGD for Managed Grafana + Prometheus via ACK |
| `compositions/secrets/` | NEW: Kro RGD for Secrets Manager via ACK |
| `gitops/addons/charts/kro-clusters/` | Enhance to support full spoke lifecycle (create, bootstrap, destroy) |
| `gitops/fleet/` | Add spoke registration via Kro ResourceGroup instances |
| `platform/backstage/templates/` | Add "Create Spoke Cluster" template that creates Kro ResourceGroup |
| `platform/infra/terraform/` | REMOVE entirely from `appmod-blueprints` — moves to `platform-engineering-on-eks` |

### 3.6 Phase 6: Tagging and Versioning

**Goal**: Enable customers to pin to specific versions of the solution.

#### 3.6.1 Semantic Versioning

- Tag releases: `v1.0.0`, `v1.1.0`, etc.
- Customers reference the repo with tags in ArgoCD:
  ```yaml
  spec:
    source:
      repoURL: https://github.com/aws-samples/appmod-blueprints
      targetRevision: v1.0.0
  ```

#### 3.6.2 GitOps Addon Versioning

- Tag addon chart versions independently
- ArgoCD `targetRevision` references tags instead of `main`
- Customers can pin addons to specific versions in their `hub-config.yaml`:
  ```yaml
  repo:
    url: https://github.com/aws-samples/appmod-blueprints
    revision: v1.0.0  # Pinned version
  ```

---

## 4. Impact Analysis

### 4.1 Files Requiring Changes

#### Terraform → Compositions Migration (High Impact)

| Current Terraform File | Action | Replacement |
|---|---|---|
| `platform/infra/terraform/common/locals.tf` | Remove from solution repo | Config logic moves to `hub-config.yaml` ConfigMap consumed by addon charts |
| `platform/infra/terraform/common/argocd.tf` | Remove from solution repo | ArgoCD bootstrap is already GitOps-native; git credentials via External Secrets |
| `platform/infra/terraform/common/gitlab.tf` | Move to `platform-engineering-on-eks` | Workshop-specific |
| `platform/infra/terraform/common/secrets.tf` | Replace with `compositions/secrets/` | ACK SecretsManager + External Secrets Operator |
| `platform/infra/terraform/common/cloudfront.tf` | Replace with `compositions/ingress/` | ACK CloudFront controller (optional) |
| `platform/infra/terraform/common/ingress-nginx.tf` | Already GitOps-native | Ingress NGINX is an ArgoCD addon chart |
| `platform/infra/terraform/common/variables.tf` | Remove from solution repo | Config via `hub-config.yaml` |
| `platform/infra/terraform/common/iam.tf` | Replace with `compositions/hub-bootstrap/` | ACK IAM controller |
| `platform/infra/terraform/common/pod-identity.tf` | Replace with K8s-native resources | Pod Identity associations deployed via ArgoCD |
| `platform/infra/terraform/common/observability.tf` | Replace with `compositions/observability/` | ACK Grafana + Prometheus |
| `platform/infra/terraform/cluster/` (entire stack) | Move to `platform-engineering-on-eks` | Cluster creation is outside the solution |
| `platform/infra/terraform/hub-config.yaml` | Move to repo root | Becomes `hub-config.yaml` at top level |
| `platform/infra/terraform/scripts/` (all) | Move to `platform-engineering-on-eks` | Workshop-specific deployment scripts |

#### GitOps (Medium Impact)

| File/Directory | Change Type | Effort |
|---|---|---|
| `gitops/addons/charts/backstage/` | Template auth provider, template Git integration | High |
| `gitops/addons/charts/keycloak/` | Make optional, support external OIDC | Medium |
| `gitops/addons/charts/gitlab/` | Make fully optional, no implicit dependencies | Medium |
| `gitops/addons/charts/kro-clusters/` | Enhance for spoke lifecycle management | High |
| `gitops/addons/charts/application-sets/` | Support external repo URLs | Low |
| `gitops/fleet/bootstrap/addons.yaml` | Parameterize repo URLs | Low |
| `gitops/fleet/bootstrap/clusters.yaml` | Support dynamic spoke registration | Medium |
| `gitops/addons/bootstrap/default/addons.yaml` | Review defaults for non-workshop use | Low |

#### Backstage (Medium Impact)

| File/Directory | Change Type | Effort |
|---|---|---|
| `backstage/app-config.yaml` | Template Git and auth integrations | Medium |
| `backstage/packages/backend/` | Support multiple Git providers in scaffolder | Medium |
| `platform/backstage/templates/` | Update `publish` steps for multi-provider | Medium |

#### Documentation (High Impact)

| File | Change Type | Effort |
|---|---|---|
| `docs/CONSUMPTION-GUIDE.md` | NEW — How to consume the solution externally (GitOps-native) | High |
| `docs/COMPOSITIONS-REFERENCE.md` | NEW — Kro RGD and CrossPlane composition documentation | High |
| `docs/MIGRATION-GUIDE.md` | NEW — Migrating from Terraform-based to GitOps-native | Medium |
| `README.md` | Update with new consumption patterns (no Terraform) | Medium |

### 4.2 Dependencies and Risks

| Risk | Mitigation |
|---|---|
| Breaking existing workshop deployments | Keep `platform-engineering-on-eks` repo with full Terraform for cluster creation; workshop creates cluster via TF then hands off to GitOps |
| ACK controller maturity | Validate ACK IAM, SecretsManager, CloudFront controllers are production-ready; fall back to CrossPlane providers if ACK gaps exist |
| Kro RGD complexity for IAM/secrets | Start with simple compositions; iterate. Keep Terraform as fallback in workshop repo |
| GitOps addon charts need dual-mode support | Use Helm conditionals (`{{- if }}`) extensively; test both modes |
| Backstage multi-provider support is complex | Start with GitHub + GitLab; add others incrementally |
| Hub self-management bootstrap chicken-and-egg | ArgoCD must be installed first (manually or via EKS addon); then it manages everything else. Document this clearly |
| Spoke cluster GitOps provisioning is new | Invest in robust Kro RGDs and CrossPlane compositions; test thoroughly; document rollback to manual cluster creation if needed |

---

## 5. Consumption Patterns (Post-Upgrade)

### Pattern 1: Full Platform (Workshop-style)
```bash
# In the platform-engineering-on-eks internal GitLab repo
./deploy.sh
# Creates EKS cluster via TF, installs ArgoCD, points at appmod-blueprints
# Platform self-manages from there
```

### Pattern 2: Bootstrap on Existing Cluster
```bash
# Customer has an existing EKS cluster
# 1. Install ArgoCD (if not already installed)
helm install argocd argo/argo-cd -n argocd --create-namespace

# 2. Apply hub-config
kubectl create configmap hub-config -n argocd --from-file=my-hub-config.yaml

# 3. Point ArgoCD at appmod-blueprints
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-bootstrap
  namespace: argocd
spec:
  source:
    repoURL: https://github.com/aws-samples/appmod-blueprints
    targetRevision: v1.0.0
    path: gitops/addons/charts/application-sets
  destination:
    server: https://kubernetes.default.svc
EOF
# Platform self-manages: IAM roles, secrets, ingress, addons — all via Kro/ACK
```

### Pattern 3: GitOps Only (Bring Your Own Cluster + ArgoCD)
```yaml
# Customer already has ArgoCD — just point at appmod-blueprints addons
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-addons
spec:
  source:
    repoURL: https://github.com/aws-samples/appmod-blueprints
    targetRevision: v1.0.0
    path: gitops/addons/charts/application-sets
```

### Pattern 4: Cherry-Pick Individual Addons
```yaml
# Customer deploys only specific addons via hub-config
clusters:
  hub:
    addons:
      enable_argocd: true
      enable_backstage: true
      enable_keycloak: false    # Using external IdP
      enable_gitlab: false      # Using GitHub
      enable_kro: true
      enable_crossplane: true
```
metadata:
  name: platform-addons
spec:
  source:
    repoURL: https://github.com/aws-samples/appmod-blueprints
    targetRevision: v1.0.0
    path: gitops/addons/charts/application-sets
```

---

## 6. Asana Task List

Below is the full breakdown of tasks organized by phase, ready to be imported into Asana.

---

### Epic 1: Hub Self-Management via Kro+ACK/CrossPlane (Foundation)

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 1.1 | Create `compositions/hub-bootstrap/` Kro RGDs | Create Kro ResourceGraphDefinitions that replace `platform/infra/terraform/common/iam.tf` and `pod-identity.tf`. IAM roles and policies created via ACK IAM controller. Pod Identity associations as native K8s resources. All driven by `hub-config.yaml` ConfigMap. | P0 | XL | — |
| 1.2 | Create `compositions/secrets/` Kro RGDs | Create Kro RGDs that replace `platform/infra/terraform/common/secrets.tf`. AWS Secrets Manager secrets created via ACK SecretsManager controller. External Secrets Operator syncs to K8s. Provider-agnostic: no hardcoded GitLab tokens. | P0 | L | 1.1 |
| 1.3 | Create `compositions/ingress/` Kro RGDs | Create Kro RGDs that replace `platform/infra/terraform/common/cloudfront.tf`. CloudFront distribution via ACK CloudFront controller (optional). Conditional on `ingress.type` in hub-config. | P1 | M | 1.1 |
| 1.4 | Create `compositions/observability/` Kro RGDs | Create Kro RGDs that replace `platform/infra/terraform/common/observability.tf`. Amazon Managed Grafana and Prometheus via ACK. | P2 | M | 1.1 |
| 1.5 | Move ALL Terraform to `platform-engineering-on-eks` repo | Move `platform/infra/terraform/` entirely to the workshop repo. This includes cluster creation, common stack, scripts, and hub-config.yaml (copy to repo root as default). Remove `platform/infra/terraform/` from `appmod-blueprints`. | P0 | L | 1.1, 1.2 |
| 1.6 | Create bootstrap guide for customers | Document the GitOps-native bootstrap flow: create EKS cluster (any tool) → install ArgoCD → apply hub-config ConfigMap → point ArgoCD at `appmod-blueprints`. No Terraform required. | P0 | M | 1.1–1.4 |
| 1.7 | Create `examples/` directory with consumption examples | Create `full-platform/`, `hub-only/`, `existing-cluster/`, `byog/` example configurations showing hub-config.yaml + ArgoCD Application YAML for each pattern. | P1 | M | 1.6 |
| 1.8 | Validate ACK controller readiness | Test ACK IAM, SecretsManager, CloudFront, Grafana controllers for production readiness. Identify gaps and document CrossPlane fallbacks. | P0 | L | — |
| 1.8 | Create `examples/` directory with consumption examples | Create `full-platform/`, `hub-only/`, `existing-cluster/`, `byog/` example configurations. | P1 | M | 1.5, 1.6 |

---

### Epic 2: Externalize Hub Configuration

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 2.1 | Extend `hub-config.yaml` schema | Add `git`, `identity`, `cicd`, `ingress` top-level sections. Document all keys. Keep backward compatibility with current schema. Move `hub-config.yaml` from `platform/infra/terraform/` to repo root. | P0 | M | — |
| 2.2 | Create hub-config ConfigMap bootstrap mechanism | Define how `hub-config.yaml` is loaded into the cluster as a ConfigMap in the `argocd` namespace. Kro compositions and addon charts consume this ConfigMap for provider-specific configuration. Document the `kubectl create configmap hub-config -n argocd --from-file=hub-config.yaml` step. | P0 | M | 2.1 |
| 2.3 | Remove `platform/infra/terraform/` directory from solution repo | Delete the entire `platform/infra/terraform/` directory from `appmod-blueprints`. All Terraform code (cluster creation, common stack, scripts, deploy scripts) has been replaced by compositions (Epic 1) or moved to `platform-engineering-on-eks` (Epic 4). | P0 | L | 1.1–1.5, 4.1–4.3 |
| 2.4 | Update addon charts to consume hub-config ConfigMap | Refactor ArgoCD addon charts to read provider configuration (git, identity, ingress) from the `hub-config` ConfigMap instead of Terraform-injected values. Key charts: `application-sets`, `backstage`, `keycloak`, `external-secrets`. | P0 | L | 2.2 |
| 2.5 | Create config validation script | Validate `hub-config.yaml` schema before bootstrap. Check required fields (`clusters.hub.name`, `clusters.hub.region`), valid provider values (`git.provider`, `identity.provider`, `ingress.type`). Warn on conflicting settings. | P2 | S | 2.1 |
| 2.6 | Create lightweight bootstrap script for solution repo | Create a `bootstrap.sh` script at repo root that guides customers through: validate hub-config → create ConfigMap → apply ArgoCD bootstrap Application. No Terraform — purely kubectl/helm commands. | P1 | M | 2.2, 2.5 |
| 2.7 | Document external config usage | Write `docs/HUB-CONFIG-GUIDE.md`: full schema reference, example configs (GitHub+Cognito, GitLab+Keycloak, GitHub+guest), how config flows to compositions and addon charts. | P1 | M | 2.1 |
| 2.8 | Create example hub-config files | Create `examples/hub-only/hub-config.yaml`, `examples/full-platform/hub-config.yaml`, `examples/byog/hub-config.yaml` showing different provider combinations. | P1 | S | 2.1, 2.7 |

---

### Epic 3: Decouple Keycloak-Backstage-GitLab

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 3.1 | Decouple ArgoCD bootstrap from GitLab | ArgoCD git credentials are now provided via External Secrets or a Kubernetes Secret created during bootstrap (not via Terraform `gitlab_personal_access_token`). Update the ArgoCD addon chart to accept generic `git_credentials` from the hub-config ConfigMap. Support GitHub PAT, GitLab PAT, or SSH key. | P0 | M | 2.4 |
| 3.2 | Make Keycloak optional in addon charts | Ensure all addon charts that depend on Keycloak (backstage, argo-workflows, kargo) handle `enable_keycloak: false` cleanly. Keycloak secrets and IAM roles are created by `compositions/hub-bootstrap/` only when `identity.provider == "keycloak"`. | P0 | M | 1.1 |
| 3.3 | Make GitLab optional in addon charts | Ensure all addon charts that reference GitLab (backstage, application-sets) handle `enable_gitlab: false` cleanly. No GitLab-specific resources when using GitHub. | P0 | M | 2.4 |
| 3.4 | Refactor Backstage Helm chart for multi-auth | Add `auth.provider` value to `gitops/addons/charts/backstage/`. Template OIDC config for Keycloak, Cognito, GitHub, guest. | P1 | L | — |
| 3.5 | Refactor Backstage Helm chart for multi-git | Add `git.provider` value. Template `app-config.yaml` integrations section for GitLab, GitHub, CodeCommit. | P1 | L | — |
| 3.6 | Update Backstage templates for multi-git | Update `publish` steps in `platform/backstage/templates/` to support `publish:gitlab` and `publish:github`. | P1 | M | 3.5 |
| 3.7 | Refactor secrets composition for provider-agnostic secrets | Update `compositions/secrets/` Kro RGDs to create secrets based on `hub-config.yaml` provider settings. No hardcoded GitLab tokens or Keycloak passwords — all driven by config. Support GitHub token, generic OIDC secrets. | P0 | L | 1.2, 3.1, 3.2, 3.3 |
| 3.8 | Update Keycloak chart for optional deployment | Ensure `enable_keycloak: false` cleanly skips all Keycloak resources including sync waves and External Secrets. | P1 | M | 3.2 |
| 3.9 | Update GitLab chart for optional deployment | Ensure `enable_gitlab: false` cleanly skips all GitLab resources. No dangling references. | P1 | S | 3.3 |
| 3.10 | Test standalone Backstage with guest auth | Validate Backstage works with `auth.provider: guest` and `git.provider: github` (no Keycloak, no GitLab). | P1 | M | 3.4, 3.5 |

---

### Epic 4: Workshop Isolation (Move to `platform-engineering-on-eks` Repo)

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 4.1 | Set up workshop structure in `platform-engineering-on-eks` repo | Create `terraform/` (for cluster creation), `scripts/`, `hub-config.yaml` in the internal GitLab repo. This repo hosts ALL Terraform code (cluster creation, GitLab PATs, workshop-specific infra) that was removed from `appmod-blueprints`. | P1 | M | — |
| 4.2 | Move ALL Terraform to `platform-engineering-on-eks` repo | Move the entire `platform/infra/terraform/` directory from `appmod-blueprints` to `platform-engineering-on-eks/terraform/`. This includes `cluster/` (EKS creation), `common/` (bootstrap — now replaced by compositions in solution repo), `database/`, `identity-center/`, `scripts/`, and `hub-config.yaml`. | P1 | L | 1.5, 4.1 |
| 4.3 | Move workshop scripts to `platform-engineering-on-eks` repo | Move `2-gitlab-init.sh`, `check-workshop-setup.sh`, `utils.sh` (with workshop logic), all `deploy.sh` scripts to the workshop repo's scripts directory. | P1 | M | 4.2 |
| 4.4 | Create workshop `deploy.sh` orchestrator in `platform-engineering-on-eks` | Single script: create EKS cluster via TF → install ArgoCD → apply hub-config ConfigMap → point ArgoCD at `appmod-blueprints` → run GitLab init. Platform self-manages from there. | P1 | M | 4.1, 4.2, 4.3 |
| 4.5 | Create workshop `hub-config.yaml` in `platform-engineering-on-eks` | Workshop-specific config with GitLab, Keycloak, all addons enabled, `peeks` prefix. References `appmod-blueprints` via versioned tag in ArgoCD `targetRevision`. | P1 | S | 2.1 |
| 4.6 | Validate workshop still works end-to-end | Full deployment test: TF creates cluster → ArgoCD installed → hub-config ConfigMap applied → ArgoCD points at `appmod-blueprints` → platform self-manages → GitLab init → all components running. | P0 | L | 4.1–4.5 |
| 4.7 | Document workshop repo relationship | Document how `platform-engineering-on-eks` creates the cluster and then hands off to `appmod-blueprints` for GitOps self-management. Define sync/update strategy. | P2 | S | 4.6 |

---

### Epic 5: GitOps for All Clusters (Hub Self-Management + Spoke Provisioning)

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 5.1 | Enhance `kro-clusters` chart for full spoke lifecycle | Support create, bootstrap, and destroy of spoke clusters via Kro ResourceGraphDefinitions. Spokes are provisioned exclusively via Kro/CrossPlane from the hub — no Terraform. | P0 | XL | 1.1 |
| 5.2 | Add spoke registration via Kro ResourceGroup | Create Kro RGD that registers an existing cluster as a spoke (creates ArgoCD cluster secret, bootstraps addons). For customers who create clusters outside of Kro. | P0 | L | 5.1 |
| 5.3 | Create "Add Spoke Cluster" Backstage template | Self-service template that creates a Kro ResourceGroup for spoke provisioning. | P1 | M | 5.1, 5.2 |
| 5.4 | Validate hub self-management end-to-end | Test the full hub self-management flow: create EKS cluster (any tool) → install ArgoCD → apply hub-config → ArgoCD deploys compositions → hub manages its own IAM, secrets, ingress, observability via Kro/ACK. | P0 | L | 1.1–1.4 |
| 5.5 | Document GitOps cluster provisioning | Write guide covering: hub self-management via compositions, spoke provisioning via Kro/CrossPlane, spoke registration for existing clusters. This is the only supported provisioning path. | P1 | M | 5.1, 5.2, 5.4 |
| 5.6 | Test full GitOps spoke lifecycle | Validate: hub self-manages → spoke created by Kro/CrossPlane → ArgoCD auto-discovers and bootstraps → spoke destroyed by Kro. Zero Terraform involvement after initial cluster creation. | P0 | L | 5.1, 5.4 |

---

### Epic 6: Versioning and Release

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 6.1 | Set up semantic versioning | Define versioning strategy. Create initial `v1.0.0` tag. Document release process. | P1 | S | 1.5, 1.6 |
| 6.2 | Add GitHub Actions for composition and chart validation | CI pipeline that validates Kro RGDs (`kubectl apply --dry-run`), Helm charts (`helm lint`, `helm template`), and runs `checkov` on compositions. | P1 | M | 1.1–1.4 |
| 6.3 | Add integration test for external consumption | CI test that simulates customer bootstrap: create ConfigMap from example hub-config → `helm template` the bootstrap Application → validate all generated resources. | P2 | L | 6.1 |
| 6.4 | Create CHANGELOG.md | Track changes per version. | P2 | S | 6.1 |
| 6.5 | Document version pinning for customers | Guide on how to pin ArgoCD `targetRevision` to specific version tags. How to upgrade between versions. | P1 | S | 6.1 |

---

### Epic 7: Documentation

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 7.1 | Create `docs/CONSUMPTION-GUIDE.md` | How to consume the solution externally: GitOps bootstrap on existing cluster, full platform, cherry-pick addons. All patterns are GitOps-native (no Terraform in solution repo). | P0 | L | 1.7 |
| 7.2 | Create `docs/COMPOSITIONS-REFERENCE.md` | Full reference for all Kro RGDs and CrossPlane compositions: purpose, inputs (hub-config keys), outputs, ACK controllers required, examples. | P1 | L | 1.1–1.4 |
| 7.3 | Create `docs/MIGRATION-GUIDE.md` | Guide for existing users to migrate from Terraform-based to GitOps-native consumption. How to move from `terraform apply` to ArgoCD bootstrap. State migration for existing deployments. | P1 | M | 1.5, 2.3 |
| 7.4 | Update root `README.md` | Add consumption patterns, quick start for external users (GitOps-native, no Terraform), link to guides. | P1 | M | 7.1 |
| 7.5 | Document current architecture (pre-migration baseline) | Document the existing cluster/common Terraform split, what each stack does, and how they interact. Serves as historical reference and migration baseline. | P0 | M | — |
| 7.6 | Create architecture decision records (ADRs) | Document key decisions: GitOps-native self-management, Kro+ACK over Terraform, provider abstraction, workshop isolation. | P2 | M | — |

---

### Epic 8: Agent Platform Extension

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 8.1 | Assess agent platform requirements on GitOps-native architecture | Identify what additional compositions/addons are needed for agent platform on EKS. Validate that Kro+ACK compositions can create the IAM roles and secrets the agent platform needs. | P1 | M | 1.2 |
| 8.2 | Create agent platform addon charts | New GitOps addon charts for agent-specific components. Bridge chart in `appmod-blueprints` references component charts in `sample-agent-platform-on-eks` (`https://github.com/aws-samples/sample-agent-platform-on-eks`). | P1 | L | 8.1 |
| 8.3 | Add agent platform IAM roles to `compositions/hub-bootstrap/` | Create conditional Kro RGDs in `compositions/hub-bootstrap/` for agent platform IAM roles (KagentRole, TofuControllerRole, LiteLLMRole, AgentCoreRole) via ACK IAM controller. Only created when `enable_agent_platform: true` in hub-config. | P1 | M | 1.1, 8.1 |
| 8.4 | Create agent platform hub-config example | Example `hub-config.yaml` for agent platform deployment showing `enable_agent_platform: true` with GitHub+Cognito (non-workshop path). | P2 | S | 8.1, 2.1 |
| 8.5 | Create agent platform bridge chart | Implement `gitops/addons/charts/agent-platform/` bridge chart that creates individual ArgoCD Applications pointing to component charts in `sample-agent-platform-on-eks`. Conditional on `agent-platform.enabled` in addons. | P1 | L | 8.1 |
| 8.6 | Add agent platform secrets to `compositions/secrets/` | Create conditional Kro RGDs in `compositions/secrets/` for agent platform secrets (Langfuse PostgreSQL password, LiteLLM master key) via ACK SecretsManager. External Secrets Operator syncs to `agent-platform` namespace. | P1 | M | 1.2, 8.1 |
| 8.7 | Create agent platform bootstrap values | Create default and environment-specific values files for the bridge chart: `gitops/addons/default/addons/agent-platform/values.yaml`, environment overrides. Add `agent-platform.enabled: false` to `gitops/addons/bootstrap/default/addons.yaml`. | P1 | S | 8.5 |
| 8.8 | Update agent platform docs for GitOps-native architecture | Update `docs/agent-platform/DESIGN.md` to remove all Terraform references (`terraform apply`, `variables.tf`, `workshop_type`). Update to show GitOps-native enablement via hub-config addons. Update `COMPONENTS.md` IAM references to use `compositions/hub-bootstrap/` Kro RGDs. | P1 | M | 8.1 |
| 8.9 | Validate agent platform on GitOps-native architecture | End-to-end test: hub self-manages via compositions → enable agent platform via hub-config → bridge chart creates ArgoCD Applications → all agent components deploy. Test with both GitHub+Cognito and GitLab+Keycloak. | P1 | L | 8.3, 8.5, 8.6 |
| 8.10 | Create agent platform consumption guide section | Add "Agent Platform" section to `docs/CONSUMPTION-GUIDE.md`: how to enable via hub-config, configure components, deploy to specific spokes. Link to `docs/agent-platform/DESIGN.md` and `sample-agent-platform-on-eks`. | P2 | M | 7.1, 8.9 |

---

### Task Summary

| Epic | Task Count | Effort Estimate |
|---|---|---|
| 1. Hub Self-Management via Kro+ACK/CrossPlane | 8 | ~5-7 weeks |
| 2. Externalize Hub Configuration | 8 | ~3-4 weeks |
| 3. Decouple Keycloak-Backstage-GitLab | 10 | ~5-6 weeks |
| 4. Workshop Isolation (to platform-engineering-on-eks) | 7 | ~2-3 weeks |
| 5. GitOps for All Clusters (Hub + Spokes) | 6 | ~4-5 weeks |
| 6. Versioning and Release | 5 | ~2 weeks |
| 7. Documentation | 6 | ~3-4 weeks |
| 8. Agent Platform Extension | 10 | ~5-7 weeks |
| **Total** | **60 tasks** | **~30-38 weeks** |

> Note: Many tasks can be parallelized across epics. Epics 1-3 are the critical path. Epic 8 depends on Epics 1-3 (GitOps-native architecture must exist before agent platform can be built on it), but Tasks 8.1-8.2 (assessment and doc alignment) can start immediately. Tasks 8.3-8.8 (bridge chart, IAM compositions, secrets) can proceed in parallel with Epics 4-7. Realistic timeline with 2-3 engineers: **14-18 weeks**.

---

## 7. Recommended Execution Order

```
Week 1-2:   [7.5] Document current state + [2.1] Extend hub-config schema + [8.1, 8.8] Assess agent platform + update docs for GitOps-native alignment
Week 3-6:   [1.1-1.4] Create all Kro+ACK compositions (parallel work)
Week 5-7:   [1.5] Move ALL Terraform to platform-engineering-on-eks + [2.2-2.4] Hub-config ConfigMap mechanism + remove TF directory
Week 5-8:   [1.8] Validate ACK controller readiness (parallel with composition work)
Week 7-10:  [3.1-3.3] Decouple providers in addon charts
Week 8-12:  [3.4-3.10] Decouple providers in Backstage
Week 9-11:  [4.1-4.6] Workshop isolation (work in platform-engineering-on-eks repo)
Week 10-12: [1.6-1.7] Bootstrap guide + examples
Week 10-13: [8.3-8.5] Agent platform compositions, bridge chart, bootstrap values
Week 11-13: [5.1-5.6] GitOps hub self-management + spoke provisioning via Kro/CrossPlane (critical path)
Week 12-14: [6.1-6.5] Versioning and release
Week 13-15: [8.6-8.7] Agent platform secrets compositions, hub-config example
Week 14-16: [7.1-7.4] Documentation + [8.10] Agent platform consumption guide
Week 15-18: [4.6, 5.6, 6.3, 8.9] End-to-end validation of all consumption patterns including agent platform
```

---

## 8. Success Criteria

1. A customer can deploy the hub platform on their existing EKS cluster by installing ArgoCD, applying their `hub-config.yaml` as a ConfigMap, and pointing ArgoCD at the `appmod-blueprints` GitHub repo with a version tag — **without forking and without Terraform**
2. A customer can provide their own `hub-config.yaml` with GitHub (not GitLab), Cognito (not Keycloak), and GitHub Actions (not Argo Workflows) — and the platform deploys correctly via GitOps self-management
3. The workshop continues to work end-to-end from the `platform-engineering-on-eks` internal GitLab repo, which creates the EKS cluster via Terraform and then hands off to `appmod-blueprints` for GitOps self-management
4. Spoke clusters can be provisioned via Kro/CrossPlane from the hub — without running Terraform
5. All Kro RGDs and CrossPlane compositions pass `kubectl apply --dry-run`, all Helm charts pass `helm lint` and `helm template`, and compositions have documented inputs/outputs
6. The agent platform deploys correctly on the GitOps-native architecture by setting `enable_agent_platform: true` in `hub-config.yaml`, with the bridge chart creating ArgoCD Applications that reference component charts in `sample-agent-platform-on-eks` (`https://github.com/aws-samples/sample-agent-platform-on-eks`)
7. The agent platform works with both workshop (GitLab+Keycloak) and non-workshop (GitHub+Cognito) configurations — no workshop-specific assumptions in the agent platform code path
8. `docs/agent-platform/DESIGN.md` is fully aligned with the GitOps-native architecture — zero references to `workshop_type`, CloudFormation, `terraform apply`, or hardcoded GitLab URLs


---

## 9. Detailed Task Breakdown for Asana

Each task below includes the specific files to change, what to change in each file, acceptance criteria, and cross-references to the relevant section of this document.

---

### EPIC 1: Hub Self-Management via Kro+ACK/CrossPlane (Foundation)

---

#### Task 1.1 — Create `compositions/hub-bootstrap/` Kro RGDs

**Doc Reference:** Section 3.1.1

**Description:**
Create Kro ResourceGraphDefinitions that replace `platform/infra/terraform/common/iam.tf` and `pod-identity.tf`. IAM roles and policies are created via ACK IAM controller. Pod Identity associations are native K8s resources. All driven by `hub-config.yaml` ConfigMap.

**Files to Create:**
- `compositions/hub-bootstrap/iam-rgd.yaml` — Kro RGD that creates IAM roles via ACK IAM controller:
  - ArgoCD hub role (for cross-account spoke management)
  - External Secrets Operator role (for Secrets Manager access)
  - Backstage role (for EKS/S3 access)
  - Karpenter role (for EC2 management)
  - CloudWatch Observability role
  - All role names parameterized with `resource_prefix` from hub-config ConfigMap
- `compositions/hub-bootstrap/pod-identity-rgd.yaml` — Kro RGD that creates Pod Identity associations as native K8s resources, deployed via ArgoCD
- `compositions/hub-bootstrap/model-storage-rgd.yaml` — Kro RGD for ML model storage S3 bucket via ACK S3 controller
- `compositions/hub-bootstrap/ray-image-rgd.yaml` — Kro RGD for Ray image build pipeline via ACK CodeBuild controller
- `compositions/hub-bootstrap/kustomization.yaml` — Kustomize overlay for deploying all RGDs
- `compositions/hub-bootstrap/README.md` — Document all RGDs, inputs (hub-config keys), ACK controllers required

**Files to Reference (source of extraction):**
- `platform/infra/terraform/common/iam.tf` — Current IAM role definitions
- `platform/infra/terraform/common/pod-identity.tf` — Current Pod Identity associations
- `platform/infra/terraform/common/model-storage.tf` — S3 bucket for ML models
- `platform/infra/terraform/common/ray-image-build.tf` — CodeBuild for Ray images

**Key Design:**
- Each RGD reads configuration from the `hub-config` ConfigMap in the `argocd` namespace
- ACK IAM controller creates IAM roles; ACK S3 controller creates buckets
- RGDs are deployed as ArgoCD Applications via the bootstrap ApplicationSet
- `resource_prefix` is parameterized — no hardcoded `peeks`

**Acceptance Criteria:**
- Kro RGDs create all IAM roles currently created by Terraform `iam.tf`
- Pod Identity associations are created as native K8s resources
- `kubectl apply --dry-run=client` validates all RGD manifests
- README documents all inputs and ACK controller dependencies
- No Terraform references in any composition file

---

#### Task 1.2 — Create `compositions/secrets/` Kro RGDs

**Doc Reference:** Section 3.1.2

**Description:**
Create Kro RGDs that replace `platform/infra/terraform/common/secrets.tf`. AWS Secrets Manager secrets are created via ACK SecretsManager controller. External Secrets Operator syncs secrets to Kubernetes.

**Files to Create:**
- `compositions/secrets/secrets-rgd.yaml` — Kro RGD that creates AWS Secrets Manager secrets via ACK:
  - Git credentials secret (provider-agnostic: accepts GitHub PAT, GitLab PAT, or SSH key)
  - Platform admin password secret
  - Identity provider secrets (conditional on `identity.provider` in hub-config)
  - Per-cluster config secrets (for spoke bootstrapping)
- `compositions/secrets/external-secrets-sync.yaml` — ExternalSecret resources that sync AWS secrets to K8s secrets
- `compositions/secrets/README.md` — Document secret structure, provider-agnostic design

**Files to Reference:**
- `platform/infra/terraform/common/secrets.tf` — Current secret structure and values

**Key Design:**
- Secrets structure is provider-agnostic: accepts `git_config`, `identity_config` from hub-config ConfigMap
- No hardcoded GitLab tokens or Keycloak passwords — all driven by config
- External Secrets Operator syncs AWS secrets to Kubernetes secrets in appropriate namespaces

**Acceptance Criteria:**
- Kro RGDs create all Secrets Manager secrets currently created by Terraform `secrets.tf`
- Secrets are provider-agnostic (no GitLab-specific structure)
- External Secrets Operator syncs secrets to K8s
- `kubectl apply --dry-run=client` validates all manifests

---

#### Task 1.3 — Create `compositions/ingress/` Kro RGDs

**Doc Reference:** Section 3.1.3

**Description:**
Create Kro RGDs that replace `platform/infra/terraform/common/cloudfront.tf`. CloudFront distribution is created via ACK CloudFront controller (optional).

**Files to Create:**
- `compositions/ingress/cloudfront-rgd.yaml` — Kro RGD that creates CloudFront distribution via ACK CloudFront controller. Conditional on `ingress.type == "cloudfront"` in hub-config.
- `compositions/ingress/README.md` — Document ingress options: `cloudfront` (ACK), `alb`, `nlb`, `custom`

**Files to Reference:**
- `platform/infra/terraform/common/cloudfront.tf` — Current CloudFront distribution with Keycloak-specific cache behavior

**Key Design:**
- Ingress NGINX remains as an ArgoCD addon chart (already GitOps-native)
- CloudFront is optional — only created when `ingress.type: cloudfront` in hub-config
- Customers with their own DNS/ingress can set `ingress.type: custom` and skip CloudFront entirely

**Acceptance Criteria:**
- Kro RGD creates CloudFront distribution when `ingress.type: cloudfront`
- No CloudFront resources when `ingress.type` is `alb`, `nlb`, or `custom`
- Customers can provide their own domain and ACM certificate via hub-config
- `kubectl apply --dry-run=client` validates all manifests

---

#### Task 1.4 — Create `compositions/observability/` Kro RGDs

**Doc Reference:** Section 3.1.4

**Description:**
Create Kro RGDs that replace `platform/infra/terraform/common/observability.tf`. Amazon Managed Grafana and Prometheus are created via ACK.

**Files to Create:**
- `compositions/observability/grafana-rgd.yaml` — Kro RGD for Amazon Managed Grafana workspace via ACK
- `compositions/observability/prometheus-rgd.yaml` — Kro RGD for Amazon Managed Prometheus workspace via ACK
- `compositions/observability/README.md` — Document observability options

**Files to Reference:**
- `platform/infra/terraform/common/observability.tf` — Current Managed Grafana + Prometheus setup

**Acceptance Criteria:**
- Kro RGDs create Managed Grafana + Managed Prometheus when enabled in hub-config
- Can be disabled entirely via hub-config addons flags
- `kubectl apply --dry-run=client` validates all manifests

---

#### Task 1.5 — Move ALL Terraform to `platform-engineering-on-eks` Repo

**Doc Reference:** Section 3.1.5, Section 3.4.1

**Description:**
Move the entire `platform/infra/terraform/` directory from `appmod-blueprints` to the `platform-engineering-on-eks` internal GitLab repo. Copy `hub-config.yaml` to repo root as a default/example. Delete `platform/infra/terraform/` from `appmod-blueprints`.

**Files to Move:**
- `platform/infra/terraform/cluster/` → `platform-engineering-on-eks/terraform/cluster/`
- `platform/infra/terraform/common/` → `platform-engineering-on-eks/terraform/common/` (kept as reference; workshop still uses TF for cluster creation)
- `platform/infra/terraform/database/` → `platform-engineering-on-eks/terraform/database/`
- `platform/infra/terraform/identity-center/` → `platform-engineering-on-eks/terraform/identity-center/`
- `platform/infra/terraform/scripts/` → `platform-engineering-on-eks/scripts/`
- `platform/infra/terraform/hub-config.yaml` → copy to `hub-config.yaml` (repo root, as default/example)

**Files to Delete from `appmod-blueprints`:**
- `platform/infra/terraform/` (entire directory after move)

**Acceptance Criteria:**
- `platform/infra/terraform/` no longer exists in `appmod-blueprints`
- `hub-config.yaml` exists at repo root as default/example
- All Terraform code is in `platform-engineering-on-eks` repo
- `appmod-blueprints` has zero `.tf` files

---

#### Task 1.6 — Create Bootstrap Guide for Customers

**Doc Reference:** Section 3.2.3

**Description:**
Document the GitOps-native bootstrap flow for customers. No Terraform required in `appmod-blueprints`.

**File to Create:** `docs/BOOTSTRAP-GUIDE.md`

**Content:**
```bash
# 1. Create EKS cluster (any tool — eksctl, CDK, Terraform, CLI)
eksctl create cluster --name hub --region us-west-2

# 2. Install ArgoCD
helm install argocd argo/argo-cd -n argocd --create-namespace

# 3. Apply hub-config as ConfigMap
kubectl create configmap hub-config -n argocd --from-file=hub-config.yaml

# 4. Point ArgoCD at appmod-blueprints
kubectl apply -f bootstrap-application.yaml

# 5. Platform self-manages from here
```

**Acceptance Criteria:**
- Guide is complete and testable by someone unfamiliar with the repo
- No Terraform steps in the guide
- Covers prerequisites (AWS CLI, kubectl, helm, EKS cluster)
- Links to example hub-config files

---

#### Task 1.7 — Create `examples/` Directory with Consumption Examples

**Doc Reference:** Section 5 (Consumption Patterns)

**Description:**
Create working example configurations that demonstrate each consumption pattern.

**Files to Create:**
- `examples/full-platform/hub-config.yaml` — Full deployment with all addons (Pattern 1)
- `examples/full-platform/bootstrap-application.yaml` — ArgoCD Application YAML
- `examples/full-platform/README.md` — Step-by-step guide
- `examples/hub-only/hub-config.yaml` — Hub cluster with minimal addons (Pattern 2)
- `examples/hub-only/bootstrap-application.yaml`
- `examples/hub-only/README.md`
- `examples/existing-cluster/hub-config.yaml` — Bootstrap on existing EKS cluster (Pattern 3)
- `examples/existing-cluster/README.md`
- `examples/byog/hub-config.yaml` — Bring Your Own Git: GitHub instead of GitLab (Pattern 4)
- `examples/byog/README.md`

**Acceptance Criteria:**
- Each example has a hub-config.yaml + ArgoCD Application YAML + README
- Examples are copy-pasteable and deployable
- No Terraform in any example (all GitOps-native)

---

#### Task 1.8 — Validate ACK Controller Readiness

**Doc Reference:** Section 4.2 (Risks — ACK maturity)

**Description:**
Test ACK IAM, SecretsManager, CloudFront, Grafana, Prometheus, S3, CodeBuild controllers for production readiness. Identify gaps and document CrossPlane fallbacks.

**Test Matrix:**
| ACK Controller | Required For | Status | CrossPlane Fallback |
|---|---|---|---|
| ACK IAM | `compositions/hub-bootstrap/iam-rgd.yaml` | TBD | `crossplane-provider-aws` IAM |
| ACK SecretsManager | `compositions/secrets/` | TBD | `crossplane-provider-aws` SecretsManager |
| ACK CloudFront | `compositions/ingress/` | TBD | `crossplane-provider-aws` CloudFront |
| ACK Grafana | `compositions/observability/` | TBD | `crossplane-provider-aws` Grafana |
| ACK Prometheus | `compositions/observability/` | TBD | Manual setup |
| ACK S3 | `compositions/hub-bootstrap/model-storage-rgd.yaml` | TBD | `crossplane-provider-aws` S3 |
| ACK EKS | `compositions/spoke-cluster/` | TBD | `crossplane-provider-aws` EKS |

**Acceptance Criteria:**
- Each ACK controller tested for: create, update, delete of target resources
- Gaps documented with CrossPlane fallback plan
- Decision matrix: which controllers use ACK vs CrossPlane Example config with all addons
- `examples/hub-only/main.tf` — Hub cluster only, minimal addons (Pattern 2)
- `examples/hub-only/hub-config.yaml`
- `examples/existing-cluster/main.tf` — Bootstrap on existing EKS cluster (Pattern 2 variant)
- `examples/existing-cluster/hub-config.yaml`
- `examples/byog/main.tf` — Bring Your Own Git: GitHub instead of GitLab (Pattern 4)
- `examples/byog/hub-config.yaml` — Config with `git.provider: github`, `enable_gitlab: false`

**Acceptance Criteria:**
- Each example has a working `main.tf` and `hub-config.yaml`
- Each example has a `README.md` explaining the pattern
- `terraform validate` passes for each example

---

### EPIC 2: Externalize Hub Configuration

---

#### Task 2.1 — Extend `hub-config.yaml` Schema and Move to Repo Root

**Doc Reference:** Section 3.2.1

**Description:**
Move `hub-config.yaml` from `platform/infra/terraform/` to the repo root and extend the schema with provider configuration sections.

**Files to Create/Change:**
- `hub-config.yaml` (repo root) — Copy from `platform/infra/terraform/hub-config.yaml` and add:
  - `git:` block with `provider` (github|gitlab|codecommit), `url`, `revision`, `basepath`
  - `identity:` block with `provider` (keycloak|cognito|okta|external) and `config` map
  - `cicd:` block with `provider` (argo-workflows|gitlab-ci|github-actions)
  - `ingress:` block with `type` (cloudfront|alb|nlb|custom), `domain`, `certificate_arn`
- Keep backward compatibility: existing `clusters.hub.addons` structure unchanged

**Acceptance Criteria:**
- `hub-config.yaml` exists at repo root with extended schema
- All new keys are documented with YAML comments
- Backward compatible with current addon flag structure
- `yq` can parse the file without errors

---

#### Task 2.2 — Create Hub-Config ConfigMap Bootstrap Mechanism

**Doc Reference:** Section 3.2.2

**Description:**
Define how `hub-config.yaml` is loaded into the cluster as a ConfigMap. Kro compositions and ArgoCD addon charts consume this ConfigMap for provider-specific configuration.

**Key Design:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: hub-config
  namespace: argocd
data:
  hub-config.yaml: |
    # Full hub-config.yaml content
```

**Files to Create:**
- Section in `docs/BOOTSTRAP-GUIDE.md` documenting the ConfigMap creation step
- Example `bootstrap-application.yaml` that references the ConfigMap

**Acceptance Criteria:**
- ConfigMap creation is documented as a bootstrap step
- Addon charts can read provider config from the ConfigMap
- Kro compositions can reference ConfigMap values

---

#### Task 2.3 — Remove `platform/infra/terraform/` Directory from Solution Repo

**Doc Reference:** Section 3.1.5, Section 3.4.1

**Description:**
Delete the entire `platform/infra/terraform/` directory from `appmod-blueprints` after all Terraform has been moved to `platform-engineering-on-eks` (Task 1.5) and replaced by compositions (Tasks 1.1-1.4).

**Files to Delete:**
- `platform/infra/terraform/` (entire directory tree including `cluster/`, `common/`, `database/`, `identity-center/`, `scripts/`)

**Acceptance Criteria:**
- Zero `.tf` files in `appmod-blueprints`
- Zero `deploy.sh` scripts in `appmod-blueprints`
- No broken references from other files (docs, scripts, CI)
- `platform/infra/` directory is either empty or removed

---

#### Task 2.4 — Update Addon Charts to Consume Hub-Config ConfigMap

**Doc Reference:** Section 3.2.2

**Description:**
Refactor ArgoCD addon charts to read provider configuration from the `hub-config` ConfigMap instead of Terraform-injected values.

**Files to Change:**
- `gitops/addons/charts/application-sets/` — Read `git.url`, `git.revision` from ConfigMap
- `gitops/addons/charts/backstage/` — Read `identity.provider`, `git.provider` from ConfigMap
- `gitops/addons/charts/external-secrets/` — Read secret store configuration from ConfigMap
- `gitops/addons/charts/keycloak/` — Read `identity.provider` to determine if Keycloak should deploy
- `gitops/fleet/bootstrap/addons.yaml` — Parameterize repo URLs from ConfigMap

**Acceptance Criteria:**
- Addon charts read provider config from ConfigMap (not hardcoded or TF-injected)
- Charts still work with default values when ConfigMap keys are missing
- No Terraform variable references in any addon chart

---

#### Task 2.5 — Create Config Validation Script

**Doc Reference:** Section 3.2.3

**File to Create:** `scripts/validate-config.sh`

**Validation Rules:**
- Required keys: `clusters`, `clusters.hub`, `clusters.hub.name`, `clusters.hub.region`
- If `git.provider` is set, validate it's one of: `github`, `gitlab`, `codecommit`
- If `identity.provider` is set, validate it's one of: `keycloak`, `cognito`, `okta`, `external`
- If `ingress.type` is set, validate it's one of: `cloudfront`, `alb`, `nlb`, `custom`
- Warn if `enable_keycloak: true` but `identity.provider` is not `keycloak`

**Acceptance Criteria:**
- Script exits 0 on valid config, exits 1 on invalid
- Clear error messages for each validation failure

---

#### Task 2.6 — Create Lightweight Bootstrap Script for Solution Repo

**Doc Reference:** Section 3.2.3

**File to Create:** `bootstrap.sh` (repo root)

**Script Flow:**
1. Validate prerequisites (kubectl, helm, yq)
2. Validate hub-config.yaml (`scripts/validate-config.sh`)
3. Create `hub-config` ConfigMap in `argocd` namespace
4. Apply ArgoCD bootstrap Application pointing at `appmod-blueprints`
5. Print status and next steps

**Acceptance Criteria:**
- Script works on a fresh EKS cluster with ArgoCD installed
- No Terraform commands — purely kubectl/helm
- Idempotent (can be run multiple times safely)

---

#### Task 2.7 — Document External Config Usage

**Doc Reference:** Section 5 (Consumption Patterns)

**File to Create:** `docs/HUB-CONFIG-GUIDE.md`

**Content:**
- Full schema reference for `hub-config.yaml`
- Example configs for: GitHub+Cognito, GitLab+Keycloak, GitHub+guest auth
- How config flows to ConfigMap → addon charts → compositions
- Migration guide from old Terraform-variable-based config to new hub-config schema

**Acceptance Criteria:**
- Document covers all config keys with descriptions
- At least 3 example configs provided
- Reviewed by team

---

#### Task 2.8 — Create Example Hub-Config Files

**Doc Reference:** Section 5 (Consumption Patterns)

**Files to Create:**
- `examples/hub-only/hub-config.yaml` — Minimal config: ArgoCD + Backstage only
- `examples/full-platform/hub-config.yaml` — All addons enabled
- `examples/byog/hub-config.yaml` — GitHub instead of GitLab, Cognito instead of Keycloak
- Each with a `README.md` explaining the use case

**Acceptance Criteria:**
- Each example is valid against the schema
- Examples are referenced from `docs/HUB-CONFIG-GUIDE.md`
- No Terraform in any example


---

### EPIC 3: Decouple Keycloak-Backstage-GitLab

---

#### Task 3.1 — Decouple ArgoCD Bootstrap from GitLab

**Doc Reference:** Section 3.3.1

**Description:**
ArgoCD git credentials are now provided via External Secrets or a Kubernetes Secret created during bootstrap — not via Terraform `gitlab_personal_access_token`. Update the ArgoCD addon chart to accept generic `git_credentials` from the hub-config ConfigMap.

**Files to Change:**
- `gitops/addons/charts/argocd/` (or equivalent bootstrap chart) — Accept generic git credentials:
  - Support GitHub PAT, GitLab PAT, or SSH key
  - Read `git.provider` and `git.url` from hub-config ConfigMap
  - Create ArgoCD repo secret with provider-appropriate credentials
- `gitops/addons/bootstrap/default/addons.yaml` — Add `git_provider: github` default

**Acceptance Criteria:**
- ArgoCD bootstrap works with GitHub PAT (no GitLab dependency)
- ArgoCD bootstrap works with GitLab PAT (backward compat)
- Git credentials are provided via K8s Secret or External Secrets, not Terraform

---

#### Task 3.2 — Make Keycloak Optional in Addon Charts

**Doc Reference:** Section 3.3.4

**Description:**
Ensure all addon charts that depend on Keycloak handle `enable_keycloak: false` cleanly. Keycloak secrets and IAM roles are created by `compositions/hub-bootstrap/` only when `identity.provider == "keycloak"` in hub-config.

**Files to Change:**
- `gitops/addons/charts/backstage/` — Make Keycloak OIDC config conditional
- `gitops/addons/charts/argo-workflows/` — Make Keycloak SSO config conditional
- `gitops/addons/charts/kargo/` — Make Keycloak SSO config conditional
- `compositions/hub-bootstrap/iam-rgd.yaml` — Wrap Keycloak IAM roles in conditional on `identity.provider`
- `compositions/secrets/secrets-rgd.yaml` — Wrap Keycloak secrets in conditional

**Acceptance Criteria:**
- When `identity.provider != "keycloak"`, no Keycloak resources are created
- When `identity.provider == "keycloak"`, behavior is identical to current
- No orphaned secrets or IAM roles when Keycloak is disabled

---

#### Task 3.3 — Make GitLab Optional in Addon Charts

**Doc Reference:** Section 3.3.1, Section 1.2

**Description:**
Ensure all addon charts that reference GitLab handle `enable_gitlab: false` cleanly. No GitLab-specific resources when using GitHub.

**Files to Change:**
- `gitops/addons/charts/backstage/` — Make GitLab integration conditional on `git.provider`
- `gitops/addons/charts/application-sets/` — Parameterize repo URLs from hub-config (not hardcoded GitLab)
- `gitops/fleet/bootstrap/` — Parameterize all repo URL references

**Acceptance Criteria:**
- No GitLab-specific resources when `git.provider: github`
- No dangling references to GitLab hostname in any chart
- ArgoCD sync completes cleanly without GitLab

---

#### Task 3.4 — Refactor Backstage Helm Chart for Multi-Auth

**Doc Reference:** Section 3.3.2

**Files to Change:**
- `gitops/addons/charts/backstage/values.yaml` — Add `auth.provider: keycloak` (keycloak|cognito|github|guest)
- `gitops/addons/charts/backstage/templates/` — Template auth section based on provider:
  - Keycloak: OIDC config with sync waves 10→15→25
  - Cognito: OIDC config with Cognito user pool
  - Guest: No external IdP
- `gitops/addons/charts/backstage/templates/keycloak-config.yaml` — Wrap in `{{- if eq .Values.auth.provider "keycloak" }}`
- `gitops/addons/charts/backstage/templates/external-secret.yaml` — Make Keycloak secret sync conditional

**Acceptance Criteria:**
- Backstage deploys with Keycloak auth (backward compat)
- Backstage deploys with guest auth (no Keycloak dependency)
- Backstage deploys with Cognito auth (new capability)

---

#### Task 3.5 — Refactor Backstage Helm Chart for Multi-Git

**Doc Reference:** Section 3.3.3

**Files to Change:**
- `gitops/addons/charts/backstage/values.yaml` — Add `git.provider: gitlab` (gitlab|github|codecommit)
- `gitops/addons/charts/backstage/templates/` — Template `app-config.yaml` integrations:
  ```yaml
  integrations:
    {{- if eq .Values.git.provider "gitlab" }}
    gitlab:
      - token: ${GIT_PASSWORD}
        host: ${GIT_HOSTNAME}
    {{- else if eq .Values.git.provider "github" }}
    github:
      - host: github.com
        token: ${GITHUB_TOKEN}
    {{- end }}
  ```
- `backstage/app-config.yaml` — Update base config for environment variable substitution

**Acceptance Criteria:**
- Backstage integrates with GitLab when `git.provider: gitlab`
- Backstage integrates with GitHub when `git.provider: github`
- Catalog discovery works with both providers

---

#### Task 3.6 — Update Backstage Templates for Multi-Git

**Doc Reference:** Section 3.3.3

**Files to Change:**
- All template YAML files in `platform/backstage/templates/` with `publish:gitlab` steps — Add conditional:
  ```yaml
  steps:
    - id: publish
      name: Publish
      action: "publish:{{ .Values.git.provider }}"
  ```
- `platform/backstage/customtemplates/*/template.yaml` — Same pattern

**Acceptance Criteria:**
- Templates publish to GitLab when `git.provider: gitlab`
- Templates publish to GitHub when `git.provider: github`
- Template parameters adapt to the Git provider

---

#### Task 3.7 — Refactor Secrets Composition for Provider-Agnostic Secrets

**Doc Reference:** Section 3.1.2, Section 1.2

**Description:**
Update `compositions/secrets/` Kro RGDs to create secrets based on hub-config provider settings. No hardcoded GitLab tokens or Keycloak passwords.

**Files to Change:**
- `compositions/secrets/secrets-rgd.yaml` — Update secret structure:
  - Git credentials: read from `git.provider` in hub-config (GitHub token, GitLab PAT, or SSH key)
  - Identity secrets: conditional on `identity.provider` (Keycloak passwords only when provider is keycloak)
  - Platform admin password: generic, not tied to `ide_password`
- `compositions/secrets/external-secrets-sync.yaml` — Update ExternalSecret resources for provider-agnostic structure

**Acceptance Criteria:**
- Secrets created with GitHub token when `git.provider: github`
- Secrets created without Keycloak block when `identity.provider != "keycloak"`
- No references to `gitlab_token`, `ide_password`, or hardcoded provider assumptions

---

#### Task 3.8 — Update Keycloak Chart for Optional Deployment

**Doc Reference:** Section 3.3.4

**Files to Change:**
- `gitops/addons/charts/keycloak/templates/*.yaml` — Verify all templates wrapped in `{{- if .Values.enable_keycloak }}`
- `gitops/addons/charts/application-sets/templates/*.yaml` — Verify Keycloak ApplicationSet is conditional
- Check for hardcoded references to Keycloak namespace/services in other charts

**Acceptance Criteria:**
- `enable_keycloak: false` results in zero Keycloak resources
- No other chart fails when Keycloak is absent
- ArgoCD sync completes cleanly without Keycloak

---

#### Task 3.9 — Update GitLab Chart for Optional Deployment

**Doc Reference:** Section 3.3.1

**Files to Change:**
- `gitops/addons/charts/gitlab/templates/*.yaml` — Verify all templates wrapped in `{{- if .Values.enable_gitlab }}`
- Check for references to GitLab hostname in other charts (backstage, argo-workflows)

**Acceptance Criteria:**
- `enable_gitlab: false` results in zero GitLab resources
- No other chart has dangling references to GitLab
- ArgoCD sync completes cleanly without GitLab

---

#### Task 3.10 — Test Standalone Backstage (Guest Auth + GitHub)

**Doc Reference:** Section 3.3.2, Section 3.3.3

**Test Configuration:**
```yaml
clusters:
  hub:
    addons:
      enable_backstage: true
      enable_keycloak: false
      enable_gitlab: false
git:
  provider: github
identity:
  provider: guest
```

**Test Steps:**
1. Deploy hub cluster with above config (via ArgoCD bootstrap)
2. Verify Backstage pod starts and is healthy
3. Verify Backstage UI loads with guest auth
4. Verify catalog discovers entities from GitHub
5. Verify a template can publish to GitHub
6. Verify no Keycloak or GitLab pods exist

**Acceptance Criteria:**
- Backstage fully functional without Keycloak and GitLab
- All 6 test steps pass
- Document any limitations


---

### EPIC 4: Workshop Isolation (Move to `platform-engineering-on-eks` Repo)

---

#### Task 4.1 — Set Up Workshop Structure in `platform-engineering-on-eks` Repo

**Doc Reference:** Section 3.4.2

**Description:**
Create the workshop-specific directory structure in the internal `platform-engineering-on-eks` GitLab repo to host ALL Terraform code and workshop scripts removed from `appmod-blueprints`.

**Files to Create (in `platform-engineering-on-eks` repo):**
- `terraform/cluster/` — EKS cluster creation (moved from `appmod-blueprints`)
- `terraform/common/` — Bootstrap resources (reference copy; solution repo uses compositions instead)
- `terraform/database/` — RDS/Aurora (moved from `appmod-blueprints`)
- `terraform/identity-center/` — AWS Identity Center (moved from `appmod-blueprints`)
- `scripts/` — All deployment and utility scripts
- `hub-config.yaml` — Workshop-specific config (populated in Task 4.5)
- `README.md` — Workshop deployment guide

**Acceptance Criteria:**
- Directory structure matches Section 3.4.2 layout
- README explains the workshop deployment flow
- Relationship to `appmod-blueprints` is documented

---

#### Task 4.2 — Move ALL Terraform to `platform-engineering-on-eks` Repo

**Doc Reference:** Section 3.1.5, Section 3.4.1

**Description:**
Move the entire `platform/infra/terraform/` directory from `appmod-blueprints` to `platform-engineering-on-eks`. This includes cluster creation, common/bootstrap stack, database, identity-center, scripts, and hub-config.yaml.

**Files to Move:**
- `platform/infra/terraform/cluster/` → `platform-engineering-on-eks/terraform/cluster/`
- `platform/infra/terraform/common/` → `platform-engineering-on-eks/terraform/common/`
- `platform/infra/terraform/common/gitlab.tf` → `platform-engineering-on-eks/terraform/gitlab.tf`
- `platform/infra/terraform/database/` → `platform-engineering-on-eks/terraform/database/`
- `platform/infra/terraform/identity-center/` → `platform-engineering-on-eks/terraform/identity-center/`
- `platform/infra/terraform/scripts/` → `platform-engineering-on-eks/scripts/`
- `platform/infra/terraform/hub-config.yaml` → copy to `hub-config.yaml` (repo root of `appmod-blueprints` as default/example)

**Files to Delete from `appmod-blueprints`:**
- `platform/infra/terraform/` (entire directory after move)

**Acceptance Criteria:**
- `platform/infra/terraform/` no longer exists in `appmod-blueprints`
- All Terraform code is in `platform-engineering-on-eks` repo
- Workshop repo's Terraform still works (terraform validate passes)

---

#### Task 4.3 — Move Workshop Scripts to `platform-engineering-on-eks` Repo

**Doc Reference:** Section 3.4.1

**Files to Move:**
- `platform/infra/terraform/scripts/utils.sh` → `platform-engineering-on-eks/scripts/utils.sh`
- `platform/infra/terraform/scripts/2-gitlab-init.sh` → `platform-engineering-on-eks/scripts/gitlab-init.sh`
- `platform/infra/terraform/scripts/check-workshop-setup.sh` → `platform-engineering-on-eks/scripts/check-setup.sh`
- `platform/infra/terraform/cluster/deploy.sh` → `platform-engineering-on-eks/scripts/deploy-cluster.sh`
- `platform/infra/terraform/common/deploy.sh` → replaced by ArgoCD bootstrap (no deploy script needed)

**Acceptance Criteria:**
- No deployment scripts remain in `appmod-blueprints`
- Workshop scripts work when called from `platform-engineering-on-eks` repo
- Scripts reference the correct paths in the workshop repo structure

---

#### Task 4.4 — Create Workshop `deploy.sh` Orchestrator in `platform-engineering-on-eks`

**Doc Reference:** Section 3.4.2

**File to Create:** `platform-engineering-on-eks/deploy.sh`

**Script Flow:**
```bash
# 1. Create EKS hub cluster via Terraform
cd terraform/cluster && terraform apply

# 2. Install ArgoCD on the hub
./scripts/bootstrap-argocd.sh

# 3. Apply workshop hub-config as ConfigMap
kubectl create configmap hub-config -n argocd --from-file=hub-config.yaml

# 4. Point ArgoCD at appmod-blueprints — platform self-manages from here
kubectl apply -f bootstrap-application.yaml

# 5. Run workshop-specific setup (GitLab init, etc.)
./scripts/gitlab-init.sh
```

**Also Create:** `platform-engineering-on-eks/destroy.sh` — Reverse order teardown

**Acceptance Criteria:**
- `deploy.sh` deploys the full workshop from scratch
- `destroy.sh` cleanly tears down everything
- Workshop deployment is identical to current behavior
- ArgoCD `targetRevision` references a versioned tag of `appmod-blueprints`

---

#### Task 4.5 — Create Workshop `hub-config.yaml` in `platform-engineering-on-eks`

**Doc Reference:** Section 3.4.2, Section 3.2.1

**File to Create:** `platform-engineering-on-eks/hub-config.yaml`

**Content:** Based on current `appmod-blueprints/platform/infra/terraform/hub-config.yaml` with additions:
```yaml
resource_prefix: peeks
domain_name: cnoe.io
git:
  provider: gitlab
identity:
  provider: keycloak
cicd:
  provider: argo-workflows
ingress:
  type: cloudfront
clusters:
  hub:
    addons:
      # All addons enabled for workshop
      enable_argocd: true
      enable_backstage: true
      enable_keycloak: true
      enable_gitlab: true
      # ... all other addons
```

**Acceptance Criteria:**
- Workshop config is self-contained in the workshop repo
- Includes all new schema keys from Section 3.2.1
- Backward compatible with current deployment

---

#### Task 4.6 — Validate Workshop End-to-End from `platform-engineering-on-eks`

**Doc Reference:** Section 4.2 (Risks)

**Test Steps:**
1. Start from clean AWS account
2. Clone `platform-engineering-on-eks` repo
3. Run `deploy.sh` (creates cluster via TF → installs ArgoCD → applies hub-config → points at `appmod-blueprints`)
4. Verify hub cluster created
5. Verify ArgoCD is running and syncing addons from `appmod-blueprints`
6. Verify Keycloak, GitLab, Backstage are running
7. Verify platform self-manages (compositions create IAM roles, secrets, etc.)
8. Run `destroy.sh`
9. Verify clean teardown

**Acceptance Criteria:**
- All 9 steps pass
- No regressions from current workshop behavior
- `appmod-blueprints` repo has zero workshop-specific code or Terraform

---

#### Task 4.7 — Document Workshop Repo Relationship

**Doc Reference:** Section 3.4

**Files to Create:**
- `platform-engineering-on-eks/docs/UPSTREAM-RELATIONSHIP.md` — How the workshop repo creates the cluster and hands off to `appmod-blueprints` for GitOps self-management
- `appmod-blueprints/docs/WORKSHOP-SEPARATION.md` — Brief note explaining that workshop code lives in `platform-engineering-on-eks`

**Content:**
- Version pinning strategy (which `appmod-blueprints` tag the workshop uses)
- How to update the workshop when `appmod-blueprints` releases a new version
- Clear boundary definition: TF for cluster creation in workshop repo, GitOps for everything else in solution repo

**Acceptance Criteria:**
- Relationship is clearly documented in both repos
- Update/sync process is defined


---

### EPIC 5: GitOps for All Clusters (Hub Self-Management + Spoke Provisioning)

---

#### Task 5.1 — Enhance `kro-clusters` Chart for Full Spoke Lifecycle

**Doc Reference:** Section 3.5.3

**Description:**
Extend the existing `kro-clusters` Helm chart to support creating, bootstrapping, and destroying spoke clusters entirely through GitOps. Spokes are provisioned exclusively via Kro/CrossPlane — no Terraform.

**Files to Change:**
- `gitops/addons/charts/kro-clusters/` — Add new Kro ResourceGraphDefinitions:
  - `spoke-cluster-rgd.yaml` — RGD that creates an EKS cluster via ACK EKS controller
  - `spoke-bootstrap-rgd.yaml` — RGD that creates ArgoCD cluster secret + External Secrets for the spoke
  - `spoke-destroy-rgd.yaml` — RGD that cleanly removes a spoke
- `gitops/fleet/kro-values/` — Add default values for spoke cluster RGDs

**Acceptance Criteria:**
- Kro RGD can create a new EKS spoke cluster via ACK
- Kro RGD can bootstrap a spoke with ArgoCD registration
- Kro RGD can destroy a spoke cleanly
- All RGDs are deployed via ArgoCD ApplicationSet

---

#### Task 5.2 — Add Spoke Registration via Kro ResourceGroup

**Doc Reference:** Section 3.5.2

**Description:**
Create a Kro RGD for registering an existing cluster as a spoke (no cluster creation — for customers who create clusters outside of Kro).

**Files to Create:**
- `gitops/addons/charts/kro/resource-groups/spoke-registration/rgd.yaml` — ResourceGraphDefinition that:
  - Creates ArgoCD cluster secret with spoke cluster credentials
  - Creates External Secrets store for the spoke
  - Triggers ArgoCD ApplicationSet to bootstrap addons on the spoke
- `gitops/addons/charts/kro/resource-groups/spoke-registration/instance-example.yaml` — Example ResourceGroup instance

**Acceptance Criteria:**
- Applying a ResourceGroup instance registers an existing cluster
- ArgoCD auto-discovers the new spoke and syncs addons
- Spoke addons are determined by labels on the cluster secret

---

#### Task 5.3 — Create "Add Spoke Cluster" Backstage Template

**Doc Reference:** Section 3.5.2

**File to Create:** `platform/backstage/templates/spoke-cluster/template.yaml`

**Template collects:** cluster name, region, environment (dev/prod/staging), addon selections
**Template creates:** Kro ResourceGroup instance (via kubectl apply)
**Template registers:** spoke in the Backstage catalog

**Acceptance Criteria:**
- Template appears in Backstage catalog
- User can fill in parameters and create a spoke
- Spoke cluster is provisioned and bootstrapped automatically

---

#### Task 5.4 — Validate Hub Self-Management End-to-End

**Doc Reference:** Section 3.5.2

**Description:**
Test the full hub self-management flow to validate that compositions correctly replace Terraform.

**Test Steps:**
1. Create EKS cluster (any tool — eksctl, CDK, or TF from workshop repo)
2. Install ArgoCD on the cluster
3. Apply hub-config as ConfigMap
4. Point ArgoCD at `appmod-blueprints`
5. Verify ArgoCD deploys ACK controllers and Kro
6. Verify `compositions/hub-bootstrap/` creates IAM roles via ACK
7. Verify `compositions/secrets/` creates Secrets Manager secrets via ACK
8. Verify `compositions/ingress/` creates CloudFront (if configured) via ACK
9. Verify `compositions/observability/` creates Managed Grafana/Prometheus (if configured)
10. Verify all platform addons are running and healthy

**Acceptance Criteria:**
- All 10 steps pass
- Hub cluster is fully self-managing via GitOps
- Zero Terraform involvement after initial cluster creation
- All AWS resources (IAM, secrets, CloudFront, etc.) created by ACK/Kro

---

#### Task 5.5 — Document GitOps Cluster Provisioning

**Doc Reference:** Section 3.5

**File to Create:** `docs/GITOPS-CLUSTER-PROVISIONING.md`

**Content:**
- Hub self-management: how compositions replace Terraform for IAM, secrets, ingress, observability
- Spoke provisioning: how to create spokes via Kro/CrossPlane from the hub
- Spoke registration: how to register existing clusters as spokes
- Step-by-step guide for both Backstage and kubectl paths
- Architecture diagram showing the self-management flow

**Acceptance Criteria:**
- Document covers hub self-management and spoke provisioning
- Includes architecture diagram
- Reviewed by team

---

#### Task 5.6 — Test Full GitOps Spoke Lifecycle

**Doc Reference:** Section 3.5.2

**Test Steps:**
1. Deploy hub cluster and verify self-management (Task 5.4)
2. Verify CrossPlane and Kro are running on hub
3. Create a spoke cluster via Kro ResourceGroup instance (`kubectl apply`)
4. Verify EKS spoke cluster is created by ACK/CrossPlane
5. Verify ArgoCD discovers the spoke and syncs addons
6. Deploy an application to the spoke via ArgoCD
7. Destroy the spoke via Kro ResourceGroup deletion
8. Verify spoke cluster is deleted and ArgoCD cluster secret is removed

**Acceptance Criteria:**
- All 8 steps pass
- Spoke lifecycle is fully managed via GitOps — zero Terraform involvement
- Spoke creation time is documented
- Spoke destruction is clean with no orphaned resources


---

### EPIC 6: Versioning and Release

---

#### Task 6.1 — Set Up Semantic Versioning

**Doc Reference:** Section 3.6.1

**Files to Create:**
- `docs/RELEASE-PROCESS.md` — Document how to create releases, version bumping rules
- `.github/workflows/release.yml` — GitHub Action to create tagged releases

**Actions:**
- Define version format: `vMAJOR.MINOR.PATCH`
- Create initial tag `v1.0.0` on the commit after all Epic 1 changes
- Document what constitutes major/minor/patch changes

**Acceptance Criteria:**
- `v1.0.0` tag exists on GitHub
- Release process is documented
- Customers can reference `targetRevision: v1.0.0` in ArgoCD Applications

---

#### Task 6.2 — Add GitHub Actions for Composition and Chart Validation

**Doc Reference:** Section 4.2 (Risks)

**File to Create:** `.github/workflows/validate.yml`

**Pipeline Steps:**
- `kubectl apply --dry-run=client` on all Kro RGDs in `compositions/`
- `helm lint` on all charts in `gitops/addons/charts/`
- `helm template` on all charts to verify rendering
- `checkov` scan on compositions for security best practices
- Run on: push to `main`, PRs targeting `main`

**Acceptance Criteria:**
- CI runs on every PR
- All compositions and charts pass validation
- Failed checks block merge

---

#### Task 6.3 — Add Integration Test for External Consumption

**Doc Reference:** Section 5 (Consumption Patterns)

**File to Create:** `.github/workflows/integration-test.yml`

**Test:**
- Create a ConfigMap from example hub-config
- `helm template` the bootstrap Application
- Validate all generated ArgoCD Application resources
- Verify compositions render correctly with example configs
- Run on: release creation

**Acceptance Criteria:**
- Integration test passes on every release
- Simulates real customer consumption pattern (GitOps bootstrap)
- Tests at least 2 consumption patterns (hub-only, full-platform)

---

#### Task 6.4 — Create CHANGELOG.md

**File to Create:** `CHANGELOG.md`

**Format:** Keep a Changelog format (https://keepachangelog.com/)

**Acceptance Criteria:**
- CHANGELOG exists with initial `v1.0.0` entry
- Updated with every release
- Documents breaking changes prominently

---

#### Task 6.5 — Document Version Pinning for Customers

**Doc Reference:** Section 3.6.1, Section 3.6.2

**File to Create:** Section in `docs/CONSUMPTION-GUIDE.md` (or standalone `docs/VERSION-PINNING.md`)

**Content:**
- How to pin ArgoCD `targetRevision` to a version tag
- How to upgrade between versions
- Breaking change policy
- Example ArgoCD Application with pinned version

**Acceptance Criteria:**
- Clear examples for ArgoCD version pinning
- Upgrade path documented


---

### EPIC 7: Documentation

---

#### Task 7.1 — Create `docs/CONSUMPTION-GUIDE.md`

**Doc Reference:** Section 5

**Description:**
Comprehensive guide for external consumption of the solution. All patterns are GitOps-native — no Terraform in the solution repo.

**Content Sections:**
1. Prerequisites (AWS account, EKS cluster, ArgoCD, kubectl, helm)
2. Pattern 1: Full Platform deployment (Section 5, Pattern 1)
3. Pattern 2: Bootstrap on Existing Cluster (Section 5, Pattern 2)
4. Pattern 3: GitOps Only / Bring Your Own Cluster + ArgoCD (Section 5, Pattern 3)
5. Pattern 4: Cherry-Pick Individual Addons (Section 5, Pattern 4)
6. Configuration reference (link to HUB-CONFIG-GUIDE.md)
7. Troubleshooting

**Acceptance Criteria:**
- Each pattern has step-by-step instructions (all GitOps-native, no Terraform)
- Each pattern has a working example config
- Tested by someone unfamiliar with the repo

---

#### Task 7.2 — Create `docs/COMPOSITIONS-REFERENCE.md`

**Doc Reference:** Section 4.1

**Description:**
Full reference documentation for all Kro RGDs and CrossPlane compositions.

**Content per Composition:**
- Description and purpose
- ACK controllers required
- Inputs (hub-config keys consumed)
- Outputs (K8s resources created, AWS resources created)
- Usage example
- Dependencies on other compositions

**Compositions to Document:**
- `compositions/hub-bootstrap/` (IAM, Pod Identity, model storage, Ray image)
- `compositions/secrets/` (Secrets Manager, External Secrets sync)
- `compositions/ingress/` (CloudFront via ACK)
- `compositions/observability/` (Managed Grafana, Managed Prometheus)
- `compositions/spoke-cluster/` (spoke lifecycle)

**Acceptance Criteria:**
- All compositions documented
- Examples are copy-pasteable
- ACK controller dependencies clearly listed

---

#### Task 7.3 — Create `docs/MIGRATION-GUIDE.md`

**Doc Reference:** Section 4.1

**Description:**
Guide for existing users to migrate from Terraform-based to GitOps-native consumption.

**Content:**
1. What changed and why (Terraform → Kro+ACK compositions)
2. Step-by-step migration from `terraform apply` to ArgoCD bootstrap
3. How to handle existing Terraform state (state rm for resources now managed by ACK)
4. How to handle custom Terraform modifications
5. Breaking changes and workarounds

**Acceptance Criteria:**
- Covers the most common migration scenarios
- State migration steps are tested
- Reviewed by someone who has used the Terraform-based approach

---

#### Task 7.4 — Update Root `README.md`

**Doc Reference:** Section 4.1

**File to Change:** `README.md` (root of appmod-blueprints)

**Changes:**
- Add "Quick Start" section with GitOps-native bootstrap (no Terraform)
- Add "For Customers" section linking to CONSUMPTION-GUIDE.md
- Add "For Workshop" section explaining that workshop code lives in `platform-engineering-on-eks`
- Update architecture diagram to show compositions and self-management flow
- Add version badge

**Acceptance Criteria:**
- README clearly communicates the GitOps-native approach
- No Terraform commands in the Quick Start
- Links to all relevant guides

---

#### Task 7.5 — Document Current Architecture (Pre-Migration Baseline)

**Doc Reference:** Section 1.3

**Description:**
Document the existing Terraform-based architecture before making changes. Serves as historical reference and migration baseline.

**File to Create:** `docs/CURRENT-ARCHITECTURE.md`

**Content:**
- Current repo structure with descriptions
- Cluster stack: what it creates, inputs, outputs, deployment flow
- Common/bootstrap stack: what it creates, inputs, outputs, deployment flow
- How `hub-config.yaml` drives both stacks
- How `utils.sh` and `deploy.sh` scripts work
- Component dependency graph (Keycloak → Backstage → GitLab)
- Known coupling issues (reference Section 1.2)

**Acceptance Criteria:**
- Accurate representation of current state
- Reviewed by original authors
- Serves as baseline for migration

---

#### Task 7.6 — Create Architecture Decision Records (ADRs)

**Doc Reference:** Section 2.1 (Design Principles)

**Files to Create:**
- `docs/ADR-001-gitops-native-self-management.md` — Why Kro+ACK over Terraform for hub self-management
- `docs/ADR-002-workshop-separation.md` — Workshop isolation to `platform-engineering-on-eks` repo
- `docs/ADR-003-provider-abstraction.md` — How Git/Identity/CICD providers are abstracted
- `docs/ADR-004-hub-config-schema.md` — Hub config schema design decisions

**Acceptance Criteria:**
- Each ADR follows standard format (Context, Decision, Consequences)
- Decisions are reviewed and approved by team


---

### EPIC 8: Agent Platform Extension

> **Reference**: The agent platform design is fully documented in [`docs/agent-platform/DESIGN.md`](./agent-platform/DESIGN.md). This epic implements that design on top of the GitOps-native architecture established by Epics 1–7. The DESIGN.md itself requires updates to align with the upgrade approach — see Task 8.8.

> **Key Principle**: The agent platform uses the same GitOps-native patterns as the rest of the platform. IAM roles and secrets are created by Kro+ACK compositions (not Terraform). The bridge chart creates ArgoCD Applications pointing to component charts in `sample-agent-platform-on-eks` (`https://github.com/aws-samples/sample-agent-platform-on-eks`).

---

#### Task 8.1 — Assess Agent Platform Requirements on GitOps-Native Architecture

**Doc Reference:** Section 2.1 (Design Principles), DESIGN.md Sections 2–6

**Description:**
Identify what additional compositions/addons are needed for agent platform on EKS. Validate that Kro+ACK compositions can create the IAM roles and secrets the agent platform needs.

**Assessment Areas:**
- IAM roles needed: KagentRole, TofuControllerRole, LiteLLMRole, AgentCoreRole (see COMPONENTS.md)
- Secrets needed: Langfuse PostgreSQL password, LiteLLM master key, API keys
- ACK controllers needed: IAM (for roles), SecretsManager (for secrets)
- Namespace and RBAC requirements
- Pod Identity associations for agent platform service accounts

**Acceptance Criteria:**
- Complete list of IAM roles, secrets, and K8s resources needed
- Validation that ACK controllers can create all required resources
- Gap analysis with CrossPlane fallback plan if needed

---

#### Task 8.2 — Create Agent Platform Addon Charts

**Doc Reference:** DESIGN.md Section 2 (Repository Changes)

**Description:**
Ensure component charts exist in `sample-agent-platform-on-eks` (`https://github.com/aws-samples/sample-agent-platform-on-eks`) for all agent platform components. The bridge chart in `appmod-blueprints` will reference these.

**Charts Required (in `sample-agent-platform-on-eks/gitops/`):**
- `kagent/` — Kubernetes Native AI Agent Framework
- `litellm/` — LLM Gateway
- `agent-gateway/` — API gateway for agent requests
- `langfuse/` — LLM Observability
- `jaeger/` — Distributed Tracing
- `tofu-controller/` — Terraform Operator
- `agent-core-components/` — AWS Bedrock Agent Core

**Acceptance Criteria:**
- All 7 component charts exist in `sample-agent-platform-on-eks`
- Each chart has `Chart.yaml`, `values.yaml`, `templates/`, `README.md`
- `helm lint` passes for each chart

---

#### Task 8.3 — Add Agent Platform IAM Roles to `compositions/hub-bootstrap/`

**Doc Reference:** DESIGN.md Security Considerations, COMPONENTS.md IAM Permissions

**Description:**
Create conditional Kro RGDs in `compositions/hub-bootstrap/` for agent platform IAM roles via ACK IAM controller. Only created when `enable_agent_platform: true` in hub-config.

**Files to Create/Change:**
- `compositions/hub-bootstrap/agent-platform-iam-rgd.yaml` — Kro RGD that creates:
  - `KagentRole` — Bedrock InvokeModel permissions
  - `TofuControllerRole` — Bedrock agent management + IAM permissions
  - `LiteLLMRole` — Bedrock InvokeModel permissions
  - `AgentCoreRole` — Bedrock Agent Core permissions
  - All conditional on `enable_agent_platform` in hub-config ConfigMap
- `compositions/hub-bootstrap/agent-platform-pod-identity-rgd.yaml` — Pod Identity associations for agent platform service accounts

**Acceptance Criteria:**
- When `enable_agent_platform: false`, no agent platform IAM roles are created
- When `enable_agent_platform: true`, all required IAM roles are created with least-privilege policies
- Role ARNs are available for the bridge chart to pass to component charts
- `kubectl apply --dry-run=client` validates all manifests

---

#### Task 8.4 — Create Agent Platform Hub-Config Example

**Doc Reference:** Section 5 (Consumption Patterns), DESIGN.md Section 6

**Files to Create:**
- `examples/agent-platform/hub-config.yaml`:
  ```yaml
  domain_name: example.com
  resource_prefix: myplatform
  git:
    provider: github
    url: https://github.com/myorg/my-platform
  identity:
    provider: cognito
  clusters:
    hub:
      addons:
        enable_argocd: true
        enable_backstage: true
        enable_keycloak: false
        enable_gitlab: false
        enable_kro: true
        enable_crossplane: true
        enable_agent_platform: true  # Agent platform enabled
  ```
- `examples/agent-platform/bootstrap-application.yaml` — ArgoCD Application YAML
- `examples/agent-platform/README.md` — Explains the agent platform deployment pattern

**Acceptance Criteria:**
- Config is valid and deployable
- Shows agent platform enabled with GitHub + Cognito (non-workshop path)
- No Terraform in the example

---

#### Task 8.5 — Create Agent Platform Bridge Chart

**Doc Reference:** DESIGN.md Section 2, Section 4

**Description:**
Implement the bridge chart at `gitops/addons/charts/agent-platform/`. This lightweight Helm chart creates individual ArgoCD Applications pointing to component charts in `sample-agent-platform-on-eks`.

**Files to Create:**
- `gitops/addons/charts/agent-platform/Chart.yaml`
- `gitops/addons/charts/agent-platform/values.yaml` — Default values:
  ```yaml
  enabled: false
  externalRepo:
    url: "https://github.com/aws-samples/sample-agent-platform-on-eks"
    revision: "main"
    basePath: "gitops/"
  global:
    namespace: "agent-platform"
    resourcePrefix: ""  # Parameterized from hub-config
  components:
    kagent: { enabled: true, path: "kagent", syncWave: "0" }
    litellm: { enabled: true, path: "litellm", syncWave: "1" }
    agentGateway: { enabled: true, path: "agent-gateway", syncWave: "2" }
    langfuse: { enabled: true, path: "langfuse", syncWave: "1" }
    jaeger: { enabled: true, path: "jaeger", syncWave: "0" }
    tofuController: { enabled: true, path: "tofu-controller", syncWave: "-1" }
    agentCore: { enabled: false, path: "agent-core-components", syncWave: "3" }
  ```
- `gitops/addons/charts/agent-platform/templates/_helpers.tpl`
- `gitops/addons/charts/agent-platform/templates/namespace.yaml`
- `gitops/addons/charts/agent-platform/templates/kagent-application.yaml` — ArgoCD Application (conditional on `.Values.enabled` AND `.Values.components.kagent.enabled`)
- Similar templates for litellm, agent-gateway, langfuse, jaeger, tofu-controller, agent-core
- `gitops/addons/charts/agent-platform/README.md`

**Key Design:**
- Each component gets its own ArgoCD Application (not monolithic)
- Sync waves control deployment order
- Each Application references a chart in `sample-agent-platform-on-eks/gitops/<component>/`
- Values passed from bridge chart to component charts via `spec.source.helm.values`

**Acceptance Criteria:**
- `helm template` with `enabled: false` produces zero resources
- `helm template` with `enabled: true` produces 7 ArgoCD Application resources
- Each Application points to the correct path in `sample-agent-platform-on-eks`
- Resource prefix is parameterized (no hardcoded `peeks`)

---

#### Task 8.6 — Add Agent Platform Secrets to `compositions/secrets/`

**Doc Reference:** DESIGN.md Security Considerations, COMPONENTS.md

**Description:**
Create conditional Kro RGDs in `compositions/secrets/` for agent platform secrets via ACK SecretsManager. External Secrets Operator syncs to `agent-platform` namespace.

**Files to Create/Change:**
- `compositions/secrets/agent-platform-secrets-rgd.yaml` — Kro RGD that creates:
  - Langfuse PostgreSQL password (via ACK SecretsManager)
  - LiteLLM master key (via ACK SecretsManager)
  - All conditional on `enable_agent_platform` in hub-config
- `gitops/addons/charts/agent-platform/templates/external-secret.yaml` — ExternalSecret that syncs agent platform secrets from AWS Secrets Manager to K8s

**Acceptance Criteria:**
- Secrets created in AWS Secrets Manager when `enable_agent_platform: true`
- ExternalSecret syncs secrets to `agent-platform` namespace
- No secrets created when agent platform is disabled

---

#### Task 8.7 — Create Agent Platform Bootstrap Values

**Doc Reference:** DESIGN.md Section 6 (Configuration Management)

**Files to Create:**
- `gitops/addons/default/addons/agent-platform/values.yaml` — Bootstrap defaults:
  ```yaml
  components:
    kagent:
      config:
        llmProvider: "bedrock"
        region: "us-east-1"
    litellm:
      config:
        replicas: 2
        providers:
          - bedrock
  ```
- `gitops/addons/environments/control-plane/addons/agent-platform/values.yaml` — Control plane override
- `gitops/addons/bootstrap/default/addons.yaml` — UPDATE: Add `agent-platform.enabled: false`

**Acceptance Criteria:**
- Default values provide sensible defaults for all components
- `addons.yaml` has the `agent-platform` entry (disabled by default)
- Environment overrides work correctly

---

#### Task 8.8 — Update Agent Platform Docs for GitOps-Native Architecture

**Doc Reference:** Section 2.1, DESIGN.md throughout

**Description:**
Update `docs/agent-platform/DESIGN.md` and supporting docs to remove all Terraform references and align with the GitOps-native architecture.

**Files to Change:**

**`docs/agent-platform/DESIGN.md`:**
- Remove all `workshop_type` / `WorkshopType` references (workshop concern, lives in `platform-engineering-on-eks`)
- Remove CloudFormation parameter references (workshop infrastructure)
- Remove `WORKSHOP_TYPE` environment variable references
- Replace `terraform apply -var="enable_agent_platform=true"` with hub-config addons approach
- Replace `platform/infra/terraform/variables.tf` references with hub-config ConfigMap
- Update Agent Gateway auth to be provider-agnostic (template JWKS URL based on `identity.provider`)
- Replace hardcoded `peeks` prefix with `{{ .Values.global.resourcePrefix }}`
- Add note that spoke clusters are provisioned via GitOps (Kro/CrossPlane)
- Update deployment flow diagrams to show GitOps bootstrap instead of Terraform
- Remove "Level 3: Infrastructure Parameter" section that references Terraform variables
- Update "Level 4: Runtime Environment Variable" to reference `ENABLE_AGENT_PLATFORM` only (not `WORKSHOP_TYPE`)

**`docs/agent-platform/README.md`:**
- Remove `terraform apply -var="workshop_type=agent-platform"` from Quick Start
- Replace with hub-config approach: set `enable_agent_platform: true` in hub-config, apply ConfigMap, ArgoCD deploys bridge chart
- Update "Disable Agent Platform" section

**`docs/agent-platform/COMPONENTS.md`:**
- Update IAM role references to use `compositions/hub-bootstrap/` Kro RGDs (not Terraform)
- Remove hardcoded account IDs from examples
- Update service account annotations to reference composition outputs

**Acceptance Criteria:**
- DESIGN.md has zero references to `workshop_type`, `WorkshopType`, `terraform apply`, or `variables.tf`
- Agent Gateway auth is provider-agnostic
- Resource prefix is parameterized throughout
- README Quick Start uses GitOps-native approach
- COMPONENTS.md references compositions, not Terraform

---

#### Task 8.9 — Validate Agent Platform on GitOps-Native Architecture (End-to-End)

**Doc Reference:** Section 8 (Success Criteria, items 6-7), DESIGN.md Section 8

**Test Scenarios:**

**Scenario A: Agent Platform with GitHub + Cognito (non-workshop)**
1. Use `examples/agent-platform/hub-config.yaml`
2. Bootstrap hub cluster via ArgoCD (GitOps-native, no TF in solution repo)
3. Verify compositions create agent platform IAM roles via ACK
4. Verify bridge chart creates 7 ArgoCD Applications
5. Verify all agent platform pods are running in `agent-platform` namespace
6. Create a test Kagent Agent CR and verify it works with Bedrock
7. Verify Langfuse and Jaeger are collecting traces
8. Disable agent platform and verify clean removal

**Scenario B: Agent Platform with GitLab + Keycloak (workshop path)**
1. Deploy from `platform-engineering-on-eks` repo (TF creates cluster → ArgoCD → hub-config → self-manages)
2. Verify agent platform works alongside full workshop stack
3. Verify Agent Gateway auth works with Keycloak OIDC

**Scenario C: Feature flag toggle**
1. Start with `enable_agent_platform: false`
2. Enable → verify deployment
3. Disable → verify clean removal
4. Re-enable → verify clean re-deployment

**Acceptance Criteria:**
- All 3 scenarios pass
- Agent platform deploys on GitOps-native architecture without forking
- Agent platform works with both GitHub+Cognito and GitLab+Keycloak
- Feature flag toggle is clean (no orphaned resources)

---

#### Task 8.10 — Create Agent Platform Consumption Guide Section

**Doc Reference:** Section 5, Task 7.1

**File to Update:** `docs/CONSUMPTION-GUIDE.md`

**Content to Add:**
- Pattern 5: Platform with Agent Platform — step-by-step guide (GitOps-native)
- How to enable agent platform via hub-config (`enable_agent_platform: true`)
- How to configure individual components (Kagent model, LiteLLM providers, etc.)
- How to deploy agent platform to specific spoke clusters only
- How to use environment overrides for dev vs prod agent platform config
- Link to `docs/agent-platform/DESIGN.md` for architecture details
- Link to `sample-agent-platform-on-eks` (`https://github.com/aws-samples/sample-agent-platform-on-eks`) for component charts

**Acceptance Criteria:**
- Agent platform consumption is documented alongside other patterns
- Step-by-step instructions are testable
- All GitOps-native — no Terraform commands
