# Appmod Blueprints: Solution Upgrade Approach

## Executive Summary

This document outlines the detailed approach to transform the `appmod-blueprints` repository from a workshop-coupled monolith into a modular, externally consumable platform engineering accelerator. The goal is to enable customers and partners to adopt this solution in their own repositories (e.g., their GitHub/GitLab repos) **without forking**, while preserving the workshop experience as one pattern of usage.

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

1. **Module-first**: Terraform code shaped as reusable modules consumable via `source = "github.com/aws-samples/appmod-blueprints//modules/hub-bootstrap?ref=v1.0.0"`
2. **Config-external**: `hub-config.yaml` lives outside the repo; customers pass their own config
3. **Provider-agnostic**: Git provider (GitHub vs GitLab), OIDC provider, and CI/CD provider are swappable via configuration
4. **GitOpsy spokes**: Spoke clusters provisioned and managed via CrossPlane/Kro through the hub cluster — NOT via Terraform. Terraform is only for the hub.
5. **Workshop as a pattern**: Workshop-specific code moves to the internal `platform-engineering-on-eks` GitLab repo, keeping `appmod-blueprints` clean as the customer-facing solution
6. **Composable components**: Keycloak, Backstage, GitLab are independently deployable addons

### 2.2 Target Repository Structure

```
appmod-blueprints/
├── modules/                          # NEW: Reusable Terraform modules
│   ├── hub-cluster/                  #   EKS hub cluster creation
│   ├── hub-bootstrap/                #   Platform bootstrap (ArgoCD, secrets, IAM)
│   ├── ingress/                      #   Ingress setup (CloudFront or custom)
│   ├── identity/                     #   Identity provider integration (Keycloak or external)
│   └── observability/                #   Grafana, Prometheus, CloudWatch
├── examples/                         # NEW: Example configurations
│   ├── full-platform/                #   Full deployment (hub + spokes + all addons)
│   ├── hub-only/                     #   Hub cluster with minimal addons
│   ├── existing-cluster/             #   Bootstrap on existing EKS cluster
│   └── byog/                         #   Bring Your Own Git (GitHub, GitLab, CodeCommit)
├── applications/                     # UNCHANGED: Sample apps
├── backstage/                        # UNCHANGED: Backstage IDP
├── gitops/                           # REFACTORED: GitOps configurations
│   ├── addons/                       #   Platform addon charts
│   ├── apps/                         #   Application deployments
│   ├── fleet/                        #   Multi-cluster management
│   ├── platform/                     #   Platform team resources
│   └── workloads/                    #   ML/AI workloads
├── platform/
│   ├── backstage/                    # UNCHANGED: Backstage templates
│   ├── infra/terraform/              # REFACTORED: Thin wrappers calling modules
│   │   ├── cluster/                  #   Calls modules/hub-cluster (hub only; spokes via GitOps)
│   │   ├── common/                   #   Calls modules/hub-bootstrap
│   │   └── hub-config.yaml           #   DEFAULT config (overridable)
│   └── validation/                   # UNCHANGED
└── docs/                             # UPDATED: Architecture + consumption guides
```

---

## 3. Detailed Change Plan

### 3.1 Phase 1: Extract Terraform Modules (Foundation)

**Goal**: Reshape Terraform code into reusable modules that customers can source from GitHub.

#### 3.1.1 Create `modules/hub-cluster/`

Extract from `platform/infra/terraform/cluster/`:

| File | Action | Details |
|---|---|---|
| `main.tf` | Extract EKS module call | Remove workshop participant role logic, make it optional |
| `locals.tf` | Parameterize | Remove hardcoded `peeks` prefix, make all values variable-driven |
| `variables.tf` | Expand | Add `existing_vpc_id`, `existing_subnet_ids`, `create_vpc` toggle |
| `outputs.tf` | Create | Export `cluster_name`, `cluster_endpoint`, `cluster_arn`, `oidc_provider_arn`, `vpc_id` |
| `versions.tf` | Copy | Pin provider versions |

Key changes:
- Remove `workshop_participant_role_arn` from required variables (make optional)
- Add `create_vpc = true` variable (false = use existing VPC)
- Remove hardcoded `hub_vpc_id` / `hub_subnet_ids` requirement when creating VPC
- Export all values needed by downstream modules

#### 3.1.2 Create `modules/hub-bootstrap/`

Extract from `platform/infra/terraform/common/`:

| Current File | Action | Details |
|---|---|---|
| `argocd.tf` | Extract | Remove GitLab PAT dependency; accept `git_credentials` as input variable |
| `gitlab.tf` | Move to `workshop/` | GitLab token creation is workshop-specific |
| `cloudfront.tf` | Extract to `modules/ingress/` | Make CloudFront optional; support custom domain/ingress |
| `secrets.tf` | Refactor | Accept secrets as input variables instead of generating internally |
| `locals.tf` | Major refactor | Remove hardcoded GitLab URLs; use `var.git_provider_config` |
| `iam.tf` | Extract | Parameterize role names and policies |
| `pod-identity.tf` | Extract | Keep as-is, well-structured |
| `ingress-nginx.tf` | Extract to `modules/ingress/` | Decouple from CloudFront |
| `model-storage.tf` | Keep | ML-specific, optional via addon flag |
| `ray-image-build.tf` | Keep | ML-specific, optional via addon flag |
| `observability.tf` | Extract to `modules/observability/` | Decouple Grafana/Prometheus setup |

Key changes to `locals.tf`:
```hcl
# BEFORE (hardcoded GitLab)
gitops_addons_repo_url = local.gitlab_domain_name != "" ? 
  "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url

# AFTER (provider-agnostic)
gitops_addons_repo_url = var.git_config.repo_url
```

New variable structure for `modules/hub-bootstrap/variables.tf`:
```hcl
variable "git_config" {
  description = "Git provider configuration"
  type = object({
    provider     = string  # "github", "gitlab", "codecommit"
    repo_url     = string
    credentials  = optional(object({
      username = string
      token    = string
    }))
    oidc_config  = optional(object({
      issuer_url = string
      client_id  = string
    }))
  })
}

variable "identity_config" {
  description = "Identity provider configuration"
  type = object({
    provider = string  # "keycloak", "cognito", "okta", "external"
    config   = optional(map(string))
  })
  default = {
    provider = "keycloak"
  }
}

variable "cicd_config" {
  description = "CI/CD provider configuration"
  type = object({
    provider = string  # "argo-workflows", "gitlab-ci", "github-actions", "codepipeline"
  })
  default = {
    provider = "argo-workflows"
  }
}

variable "hub_config" {
  description = "Hub configuration (replaces hub-config.yaml)"
  type = any  # Accepts the full hub-config.yaml structure
}
```

#### 3.1.3 Create `modules/ingress/`

Extract from `cloudfront.tf` + `ingress-nginx.tf`:
- Make CloudFront optional (`var.create_cloudfront = true`)
- Support custom domain with ACM certificate
- Support ALB Ingress Controller as alternative
- Export ingress endpoint for downstream use

#### 3.1.4 Refactor Existing Stacks as Thin Wrappers

`platform/infra/terraform/cluster/main.tf` becomes:
```hcl
module "hub" {
  source = "../../modules/hub-cluster"
  # or: source = "github.com/aws-samples/appmod-blueprints//modules/hub-cluster?ref=v1.0.0"
  
  cluster_name       = var.clusters.hub.name
  kubernetes_version = var.clusters.hub.kubernetes_version
  region             = var.clusters.hub.region
  # ...
}
# Spoke clusters are NOT created here — they are provisioned via
# CrossPlane/Kro from the hub cluster through GitOps (see Section 3.5)
```

### 3.2 Phase 2: Externalize Hub Configuration

**Goal**: Allow customers to use `hub-config.yaml` externally, passing environments to the TF module.

#### 3.2.1 Changes to `hub-config.yaml`

Current location: `platform/infra/terraform/hub-config.yaml` (embedded in repo)

Target: The file in the repo becomes a **default/example**. Customers provide their own.

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
    existing_cluster: false            # NEW: true = skip cluster creation
    existing_vpc_id: ""                # NEW: use existing VPC
    addons:
      enable_argocd: true
      enable_keycloak: false           # Customer uses Cognito instead
      enable_backstage: true
      enable_gitlab: false             # Customer uses GitHub instead
      # ...
```

#### 3.2.2 Changes to `utils.sh`

| Change | Details |
|---|---|
| Remove `WORKSHOP_CLUSTERS` logic | Move to `workshop/scripts/utils.sh` |
| Remove `WS_PARTICIPANT_ROLE_ARN` | Workshop-specific |
| Remove `USER1_PASSWORD` / `IDE_PASSWORD` coupling | Accept generic `PLATFORM_ADMIN_PASSWORD` |
| Make `CONFIG_FILE` truly external | `CONFIG_FILE=${CONFIG_FILE:-"./hub-config.yaml"}` (current dir, not repo path) |
| Remove `update_workshop_var()` | Workshop-specific |

#### 3.2.3 Changes to `deploy.sh` Scripts

Both `cluster/deploy.sh` and `common/deploy.sh`:
- Remove workshop-specific environment variable setup
- Accept `CONFIG_FILE` as the only required input
- Remove `SKIP_GITLAB` flag (handled by `git.provider` in config)
- Add validation for required config keys

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

**Goal**: Move all workshop-specific code to the internal `platform-engineering-on-eks` GitLab repo. The `appmod-blueprints` repo becomes a clean, customer-facing solution with zero workshop concerns.

#### 3.4.1 Files to Move

| Current Location | Destination (platform-engineering-on-eks repo) | Reason |
|---|---|---|
| `platform/infra/terraform/common/gitlab.tf` | `platform-engineering-on-eks` repo terraform directory | GitLab PAT creation is workshop-specific |
| Workshop logic in `utils.sh` | `platform-engineering-on-eks` repo scripts | `WORKSHOP_CLUSTERS`, `update_workshop_var()` |
| `platform/infra/terraform/scripts/2-gitlab-init.sh` | `platform-engineering-on-eks` repo scripts | GitLab initialization |
| `platform/infra/terraform/scripts/check-workshop-setup.sh` | `platform-engineering-on-eks` repo scripts | Workshop validation |
| CloudFormation bootstrap references | `platform-engineering-on-eks` repo cloudformation directory | Workshop Studio setup |
| `backstage_image` default (`public.ecr.aws/seb-demo/backstage:latest`) | `platform-engineering-on-eks` repo config | Workshop-specific image |

#### 3.4.2 Workshop in `platform-engineering-on-eks` Repo

The internal `platform-engineering-on-eks` GitLab repo becomes the workshop-specific layer that consumes `appmod-blueprints` as an upstream dependency:

```
platform-engineering-on-eks/          # Internal GitLab repo (workshop)
├── hub-config.yaml                   # Workshop-specific config (GitLab, Keycloak, all addons)
├── deploy.sh                         # Orchestrates full workshop deployment
├── destroy.sh                        # Full cleanup
├── terraform/
│   ├── main.tf                       # Sources modules from appmod-blueprints via tag
│   ├── gitlab.tf                     # GitLab PAT and project creation
│   ├── workshop-overrides.tf         # Workshop-specific TF resources
│   └── variables.tf                  # Workshop-specific variables
├── scripts/
│   ├── utils.sh                      # Workshop-specific utilities
│   ├── gitlab-init.sh                # GitLab repo initialization
│   └── check-setup.sh               # Workshop validation
├── content/                          # Workshop content and instructions
└── README.md                         # Workshop deployment guide
```

The workshop repo references `appmod-blueprints` modules:
```hcl
# platform-engineering-on-eks/terraform/main.tf
module "hub_cluster" {
  source = "github.com/aws-samples/appmod-blueprints//modules/hub-cluster?ref=v1.0.0"
  # ...
}
module "hub_bootstrap" {
  source = "github.com/aws-samples/appmod-blueprints//modules/hub-bootstrap?ref=v1.0.0"
  # ...
}
```

### 3.5 Phase 5: GitOps for Spoke Clusters (CrossPlane/Kro)

**Goal**: Manage spoke clusters via the platform (GitOps) rather than Terraform.

#### 3.5.1 Current State

Spoke clusters are created by `platform/infra/terraform/cluster/` alongside the hub. This means customers must run Terraform to add/remove spokes.

#### 3.5.2 Target State

- Hub cluster creation remains in Terraform (or can be replaced with eksctl, CDK, CLI)
- Spoke clusters are provisioned exclusively via Kro ResourceGraphDefinitions or CrossPlane from the hub
- Terraform spoke creation is removed from `platform/infra/terraform/cluster/`
- ArgoCD ApplicationSets auto-discover and bootstrap new spokes
- Backstage templates allow self-service spoke creation

#### 3.5.3 Changes Required

| Component | Change |
|---|---|
| `platform/infra/terraform/cluster/` | Remove spoke creation from Terraform; hub-only going forward |
| `gitops/addons/charts/kro-clusters/` | Enhance to support full spoke lifecycle (create, bootstrap, destroy) |
| `gitops/fleet/` | Add spoke registration via Kro ResourceGroup instances |
| `platform/backstage/templates/` | Add "Create Spoke Cluster" template that creates Kro ResourceGroup |
| `platform/infra/terraform/cluster/` | Remove spoke cluster Terraform code; spokes are GitOps-only |

### 3.6 Phase 6: Tagging and Versioning

**Goal**: Enable customers to pin to specific versions of the solution.

#### 3.6.1 Semantic Versioning

- Tag releases: `v1.0.0`, `v1.1.0`, etc.
- Customers reference modules with tags:
  ```hcl
  module "hub" {
    source = "github.com/aws-samples/appmod-blueprints//modules/hub-cluster?ref=v1.0.0"
  }
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

#### Terraform (High Impact)

| File | Change Type | Effort |
|---|---|---|
| `platform/infra/terraform/common/locals.tf` | Major refactor — remove GitLab hardcoding, parameterize all URLs | High |
| `platform/infra/terraform/common/argocd.tf` | Decouple from GitLab PAT, accept generic git credentials | Medium |
| `platform/infra/terraform/common/gitlab.tf` | Move to `workshop/` | Low |
| `platform/infra/terraform/common/secrets.tf` | Refactor to accept external secrets, remove workshop assumptions | High |
| `platform/infra/terraform/common/cloudfront.tf` | Extract to `modules/ingress/`, make optional | Medium |
| `platform/infra/terraform/common/ingress-nginx.tf` | Extract to `modules/ingress/` | Medium |
| `platform/infra/terraform/common/variables.tf` | Major refactor — add `git_config`, `identity_config`, `cicd_config` | High |
| `platform/infra/terraform/common/main.tf` | Refactor to call modules | Medium |
| `platform/infra/terraform/common/iam.tf` | Parameterize role names | Medium |
| `platform/infra/terraform/common/observability.tf` | Extract to `modules/observability/` | Medium |
| `platform/infra/terraform/cluster/main.tf` | Refactor to call `modules/hub-cluster`; remove spoke cluster creation (spokes move to GitOps) | Medium |
| `platform/infra/terraform/cluster/locals.tf` | Remove workshop participant role logic | Low |
| `platform/infra/terraform/cluster/variables.tf` | Add `create_vpc`, `existing_vpc_id` toggles | Medium |
| `platform/infra/terraform/hub-config.yaml` | Add `git`, `identity`, `cicd`, `ingress` sections | Medium |
| `platform/infra/terraform/scripts/utils.sh` | Remove workshop logic, make CONFIG_FILE truly external | High |
| `platform/infra/terraform/cluster/deploy.sh` | Simplify, remove workshop env vars | Medium |
| `platform/infra/terraform/common/deploy.sh` | Simplify, remove `SKIP_GITLAB` | Medium |

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
| `docs/CONSUMPTION-GUIDE.md` | NEW — How to consume the solution externally | High |
| `docs/MODULE-REFERENCE.md` | NEW — Terraform module documentation | High |
| `docs/MIGRATION-GUIDE.md` | NEW — Migrating from fork-based to module-based | Medium |
| `platform/infra/terraform/README.md` | Update for new module structure | Medium |
| `README.md` | Update with new consumption patterns | Medium |

### 4.2 Dependencies and Risks

| Risk | Mitigation |
|---|---|
| Breaking existing workshop deployments | Keep `platform-engineering-on-eks` repo as a fully functional workshop layer consuming `appmod-blueprints` modules; test both paths in CI |
| Module versioning complexity | Start with a single version for all modules; split later if needed |
| GitOps addon charts need dual-mode support | Use Helm conditionals (`{{- if }}`) extensively; test both modes |
| Backstage multi-provider support is complex | Start with GitHub + GitLab; add others incrementally |
| Spoke cluster GitOps provisioning is new | Invest in robust Kro RGDs and CrossPlane compositions; test thoroughly; document rollback to manual cluster creation if needed |

---

## 5. Consumption Patterns (Post-Upgrade)

### Pattern 1: Full Platform (Workshop-style)
```bash
# In the platform-engineering-on-eks internal GitLab repo
./deploy.sh
```

### Pattern 2: Hub Only on Existing Cluster
```hcl
# Customer's Terraform
module "platform_bootstrap" {
  source = "github.com/aws-samples/appmod-blueprints//modules/hub-bootstrap?ref=v1.0.0"
  
  hub_config     = yamldecode(file("./my-hub-config.yaml"))
  git_config     = {
    provider = "github"
    repo_url = "https://github.com/myorg/my-platform"
  }
  identity_config = {
    provider = "cognito"
  }
}
```

### Pattern 3: GitOps Only (Bring Your Own Cluster)
```yaml
# Customer points ArgoCD to appmod-blueprints addons
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
# Customer deploys only specific addons
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

---

## 6. Asana Task List

Below is the full breakdown of tasks organized by phase, ready to be imported into Asana.

---

### Epic 1: Extract Terraform Modules (Foundation)

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 1.1 | Create `modules/hub-cluster/` module | Extract EKS hub cluster creation from `platform/infra/terraform/cluster/` into a reusable module with `variables.tf`, `outputs.tf`, `main.tf`, `versions.tf`. Support existing VPC and new VPC creation modes. | P0 | L | — |
| 1.2 | Create `modules/hub-bootstrap/` module | Extract platform bootstrap from `platform/infra/terraform/common/`. Parameterize git provider, identity provider, and CI/CD provider. Remove GitLab hardcoding from `locals.tf`. | P0 | XL | 1.1 |
| 1.3 | Create `modules/ingress/` module | Extract `cloudfront.tf` + `ingress-nginx.tf` into a standalone module. Make CloudFront optional. Support custom domain with ACM. | P1 | M | 1.2 |
| 1.4 | Create `modules/observability/` module | Extract `observability.tf` (Managed Grafana, Prometheus) into a standalone module. | P2 | M | 1.2 |
| 1.5 | Refactor `platform/infra/terraform/cluster/` as thin wrapper | Replace inline resources with call to `modules/hub-cluster`. Remove spoke cluster creation from Terraform (spokes move to GitOps via CrossPlane/Kro — see Epic 5). | P0 | M | 1.1 |
| 1.6 | Refactor `platform/infra/terraform/common/` as thin wrapper | Replace inline resources with calls to `modules/hub-bootstrap`, `modules/ingress`, `modules/observability`. | P0 | L | 1.2, 1.3, 1.4 |
| 1.7 | Add module output documentation | Document all module inputs/outputs in README.md for each module. | P1 | M | 1.1–1.4 |
| 1.8 | Create `examples/` directory with consumption examples | Create `full-platform/`, `hub-only/`, `existing-cluster/`, `byog/` example configurations. | P1 | M | 1.5, 1.6 |

---

### Epic 2: Externalize Hub Configuration

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 2.1 | Extend `hub-config.yaml` schema | Add `git`, `identity`, `cicd`, `ingress` top-level sections. Document all keys. Keep backward compatibility with current schema. | P0 | M | — |
| 2.2 | Refactor `utils.sh` to remove workshop logic | Remove `WORKSHOP_CLUSTERS`, `WS_PARTICIPANT_ROLE_ARN`, `update_workshop_var()`. Make `CONFIG_FILE` default to current directory. | P0 | M | — |
| 2.3 | Refactor `cluster/deploy.sh` | Remove workshop-specific env var setup. Accept `CONFIG_FILE` as primary input. Add config validation. | P1 | S | 2.2 |
| 2.4 | Refactor `common/deploy.sh` | Remove `SKIP_GITLAB` flag. Derive Git provider from config. Add config validation. | P1 | S | 2.2 |
| 2.5 | Refactor `locals.tf` in common stack | Replace hardcoded GitLab URLs with `var.git_config.repo_url`. Remove `gitlab_domain_name` conditionals. | P0 | L | 2.1 |
| 2.6 | Refactor `variables.tf` in common stack | Add `git_config`, `identity_config`, `cicd_config` variable blocks. Deprecate old individual variables. | P0 | M | 2.1 |
| 2.7 | Create config validation script | Validate `hub-config.yaml` schema before deployment. Check required fields, valid provider values. | P2 | S | 2.1 |
| 2.8 | Document external config usage | Write guide for customers on how to create and use their own `hub-config.yaml`. | P1 | M | 2.1 |

---

### Epic 3: Decouple Keycloak-Backstage-GitLab

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 3.1 | Decouple ArgoCD bootstrap from GitLab | Remove `gitlab_personal_access_token` dependency from `argocd.tf`. Accept `git_credentials` as input variable. Support GitHub PAT, GitLab PAT, or SSH key. | P0 | M | 2.5 |
| 3.2 | Make Keycloak optional in Terraform | Conditionally create Keycloak secrets and IAM roles based on `identity.provider` config. | P0 | M | 2.6 |
| 3.3 | Make GitLab optional in Terraform | Conditionally include GitLab provider and resources based on `git.provider` config. Remove GitLab provider requirement when using GitHub. | P0 | M | 2.6 |
| 3.4 | Refactor Backstage Helm chart for multi-auth | Add `auth.provider` value to `gitops/addons/charts/backstage/`. Template OIDC config for Keycloak, Cognito, GitHub, guest. | P1 | L | — |
| 3.5 | Refactor Backstage Helm chart for multi-git | Add `git.provider` value. Template `app-config.yaml` integrations section for GitLab, GitHub, CodeCommit. | P1 | L | — |
| 3.6 | Update Backstage templates for multi-git | Update `publish` steps in `platform/backstage/templates/` to support `publish:gitlab` and `publish:github`. | P1 | M | 3.5 |
| 3.7 | Refactor `secrets.tf` for provider-agnostic secrets | Accept external secrets as input. Remove assumption of GitLab token in secret structure. Support GitHub token, generic OIDC secrets. | P0 | L | 3.1, 3.2, 3.3 |
| 3.8 | Update Keycloak chart for optional deployment | Ensure `enable_keycloak: false` cleanly skips all Keycloak resources including sync waves and External Secrets. | P1 | M | 3.2 |
| 3.9 | Update GitLab chart for optional deployment | Ensure `enable_gitlab: false` cleanly skips all GitLab resources. No dangling references. | P1 | S | 3.3 |
| 3.10 | Test standalone Backstage with guest auth | Validate Backstage works with `auth.provider: guest` and `git.provider: github` (no Keycloak, no GitLab). | P1 | M | 3.4, 3.5 |

---

### Epic 4: Workshop Isolation (Move to `platform-engineering-on-eks` Repo)

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 4.1 | Set up workshop structure in `platform-engineering-on-eks` repo | Create `terraform/`, `scripts/`, `hub-config.yaml` in the internal GitLab repo to host workshop-specific code. | P1 | S | — |
| 4.2 | Move `gitlab.tf` to `platform-engineering-on-eks` repo | Move GitLab PAT creation and project management to the workshop repo's Terraform directory. Remove from `appmod-blueprints`. | P1 | S | 3.3 |
| 4.3 | Move workshop scripts to `platform-engineering-on-eks` repo | Move `2-gitlab-init.sh`, `check-workshop-setup.sh`, workshop logic from `utils.sh` to the workshop repo's scripts directory. | P1 | M | 2.2 |
| 4.4 | Create workshop `deploy.sh` orchestrator in `platform-engineering-on-eks` | Single script that sources `appmod-blueprints` modules and calls them in correct order with workshop-specific config. | P1 | M | 4.1, 4.2, 4.3 |
| 4.5 | Create workshop `hub-config.yaml` in `platform-engineering-on-eks` | Workshop-specific config with GitLab, Keycloak, all addons enabled, `peeks` prefix. References `appmod-blueprints` modules via tag. | P1 | S | 2.1 |
| 4.6 | Validate workshop still works end-to-end | Full deployment test of workshop path from `platform-engineering-on-eks` repo after refactoring. | P0 | L | 4.1–4.5 |
| 4.7 | Document workshop repo relationship | Document how `platform-engineering-on-eks` consumes `appmod-blueprints` as upstream. Define sync/update strategy. | P2 | S | 4.6 |

---

### Epic 5: GitOps Spoke Management (CrossPlane/Kro)

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 5.1 | Enhance `kro-clusters` chart for full spoke lifecycle | Support create, bootstrap, and destroy of spoke clusters via Kro ResourceGraphDefinitions. This is the primary mechanism for spoke provisioning. | P0 | XL | — |
| 5.2 | Add spoke registration via Kro ResourceGroup | Create Kro RGD that registers an existing cluster as a spoke (creates ArgoCD cluster secret, bootstraps addons). | P0 | L | 5.1 |
| 5.3 | Create "Add Spoke Cluster" Backstage template | Self-service template that creates a Kro ResourceGroup for spoke provisioning. | P1 | M | 5.1, 5.2 |
| 5.4 | Remove spoke creation from Terraform cluster stack | Remove spoke cluster Terraform code from `platform/infra/terraform/cluster/`. Cluster stack becomes hub-only. Spokes are exclusively GitOps-managed. | P0 | M | 5.1 |
| 5.5 | Document GitOps spoke provisioning | Write guide for provisioning spokes via Kro/CrossPlane. This is the only supported spoke provisioning path. | P1 | M | 5.1, 5.2 |
| 5.6 | Test full GitOps spoke lifecycle | Validate: hub created by TF → spoke created by Kro/CrossPlane → ArgoCD auto-discovers and bootstraps → spoke destroyed by Kro. | P0 | L | 5.1, 5.4 |

---

### Epic 6: Versioning and Release

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 6.1 | Set up semantic versioning | Define versioning strategy. Create initial `v1.0.0` tag. Document release process. | P1 | S | 1.5, 1.6 |
| 6.2 | Add GitHub Actions for module validation | CI pipeline that validates Terraform modules (`fmt`, `validate`, `tfsec`). | P1 | M | 1.1–1.4 |
| 6.3 | Add integration test for external consumption | CI test that sources modules from the repo (simulating customer usage). | P2 | L | 6.1 |
| 6.4 | Create CHANGELOG.md | Track changes per version. | P2 | S | 6.1 |
| 6.5 | Document module pinning for customers | Guide on how to pin to specific versions in Terraform and ArgoCD. | P1 | S | 6.1 |

---

### Epic 7: Documentation

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 7.1 | Create `docs/CONSUMPTION-GUIDE.md` | How to consume the solution externally: module-based, GitOps-only, cherry-pick addons. | P0 | L | 1.8 |
| 7.2 | Create `docs/MODULE-REFERENCE.md` | Full reference for all Terraform modules: inputs, outputs, examples. | P1 | L | 1.7 |
| 7.3 | Create `docs/MIGRATION-GUIDE.md` | Guide for existing users to migrate from fork-based to module-based consumption. | P1 | M | 1.5, 1.6 |
| 7.4 | Update root `README.md` | Add consumption patterns, quick start for external users, link to guides. | P1 | M | 7.1 |
| 7.5 | Document current Terraform split | Document the existing cluster/common split, what each stack does, and how they interact. | P0 | M | — |
| 7.6 | Create architecture decision records (ADRs) | Document key decisions: module structure, provider abstraction, workshop isolation. | P2 | M | — |

---

### Epic 8: Agent Platform Extension

| # | Task | Description | Priority | Effort | Dependencies |
|---|---|---|---|---|---|
| 8.1 | Assess agent platform requirements on modular architecture | Identify what additional modules/addons are needed for agent platform on EKS. | P1 | M | 1.2 |
| 8.2 | Create agent platform addon charts | New GitOps addon charts for agent-specific components. | P1 | L | 8.1 |
| 8.3 | Create agent platform hub-config example | Example `hub-config.yaml` for agent platform deployment. | P2 | S | 8.1, 2.1 |
| 8.4 | Validate agent platform on modular architecture | End-to-end test of agent platform using the new module-based approach. | P1 | L | 8.1, 8.2 |

---

### Task Summary

| Epic | Task Count | Effort Estimate |
|---|---|---|
| 1. Extract Terraform Modules | 8 | ~5-7 weeks |
| 2. Externalize Hub Configuration | 8 | ~3-4 weeks |
| 3. Decouple Keycloak-Backstage-GitLab | 10 | ~5-6 weeks |
| 4. Workshop Isolation (to platform-engineering-on-eks) | 7 | ~2-3 weeks |
| 5. GitOps Spoke Management | 6 | ~4-5 weeks |
| 6. Versioning and Release | 5 | ~2 weeks |
| 7. Documentation | 6 | ~3-4 weeks |
| 8. Agent Platform Extension | 10 | ~5-7 weeks |
| **Total** | **60 tasks** | **~30-38 weeks** |

> Note: Many tasks can be parallelized across epics. Epics 1-3 are the critical path. Epic 8 depends on Epics 1-3 (modular architecture must exist before agent platform can be built on it), but Tasks 8.1-8.2 (doc alignment) can start immediately. Tasks 8.4-8.8 (bridge chart, IAM, secrets) can proceed in parallel with Epics 4-7. Realistic timeline with 2-3 engineers: **14-18 weeks**.

---

## 7. Recommended Execution Order

```
Week 1-2:   [7.5] Document current state + [2.1] Extend hub-config schema + [8.1, 8.2] Update agent platform docs for modular alignment
Week 3-6:   [1.1-1.4] Extract all Terraform modules (parallel work)
Week 5-8:   [2.2-2.6] Externalize configuration (overlaps with module work)
Week 7-10:  [3.1-3.3] Decouple providers in Terraform
Week 8-12:  [3.4-3.10] Decouple providers in GitOps/Backstage
Week 9-11:  [4.1-4.6] Workshop isolation (work in platform-engineering-on-eks repo)
Week 10-12: [1.5-1.6] Refactor existing stacks as thin wrappers
Week 10-13: [8.3-8.5] Agent platform hub-config, bridge chart, bootstrap values
Week 11-13: [5.1-5.6] GitOps spoke management via CrossPlane/Kro (critical path)
Week 12-14: [6.1-6.5] Versioning and release
Week 13-15: [8.6-8.8] Agent platform IAM roles, secrets, hub-config example
Week 14-16: [7.1-7.4] Documentation + [8.10] Agent platform consumption guide
Week 15-18: [4.6, 5.6, 6.3, 8.9] End-to-end validation of all consumption patterns including agent platform
```

---

## 8. Success Criteria

1. A customer can deploy the hub platform on their existing EKS cluster by sourcing Terraform modules from the appmod-blueprints GitHub repo with a version tag — **without forking**
2. A customer can provide their own `hub-config.yaml` with GitHub (not GitLab), Cognito (not Keycloak), and GitHub Actions (not Argo Workflows) — and the platform deploys correctly
3. The workshop continues to work end-to-end from the `platform-engineering-on-eks` internal GitLab repo, consuming `appmod-blueprints` modules via versioned tags
4. Spoke clusters can be provisioned via Kro/CrossPlane from the hub — without running Terraform
5. All Terraform modules pass `terraform validate`, `tfsec`, and have documented inputs/outputs
6. The agent platform deploys correctly on the modular architecture by setting `enable_agent_platform: true` in `hub-config.yaml`, with the bridge chart creating ArgoCD Applications that reference component charts in `sample-agent-platform-on-eks` (`https://github.com/aws-samples/sample-agent-platform-on-eks`)
7. The agent platform works with both workshop (GitLab+Keycloak) and non-workshop (GitHub+Cognito) configurations — no workshop-specific assumptions in the agent platform code path
8. `docs/agent-platform/DESIGN.md` is fully aligned with the modular architecture — zero references to `workshop_type`, CloudFormation, or hardcoded GitLab URLs


---

## 9. Detailed Task Breakdown for Asana

Each task below includes the specific files to change, what to change in each file, acceptance criteria, and cross-references to the relevant section of this document.

---

### EPIC 1: Extract Terraform Modules (Foundation)

---

#### Task 1.1 — Create `modules/hub-cluster/` Module

**Doc Reference:** Section 3.1.1

**Description:**
Extract the EKS hub cluster creation logic from `platform/infra/terraform/cluster/` into a new reusable Terraform module at `modules/hub-cluster/`.

**Files to Create:**
- `modules/hub-cluster/main.tf` — EKS cluster resource, VPC (conditional), node groups. Extracted from `platform/infra/terraform/cluster/main.tf`. Remove the `aws_cloudformation_stack.usage_tracking` resource (that stays in the wrapper). Remove any `workshop_participant_role_arn` logic from EKS access entries — make it an optional input instead.
- `modules/hub-cluster/variables.tf` — New variables:
  - `cluster_name` (string, required)
  - `kubernetes_version` (string, default `"1.32"`)
  - `region` (string, required)
  - `auto_mode` (bool, default `true`)
  - `create_vpc` (bool, default `true`) — when `false`, use `existing_vpc_id` and `existing_subnet_ids`
  - `existing_vpc_id` (string, optional)
  - `existing_subnet_ids` (list(string), optional)
  - `resource_prefix` (string, default `""`)
  - `additional_access_entries` (map, optional) — replaces hardcoded `workshop_participant_role_arn`
  - `tags` (map(string), optional)
- `modules/hub-cluster/outputs.tf` — Export: `cluster_name`, `cluster_endpoint`, `cluster_arn`, `cluster_certificate_authority`, `oidc_provider_arn`, `oidc_issuer`, `vpc_id`, `subnet_ids`, `cluster_security_group_id`
- `modules/hub-cluster/versions.tf` — Copy from `platform/infra/terraform/cluster/versions.tf`, pin provider versions
- `modules/hub-cluster/data.tf` — Extract `data.aws_availability_zones`, `data.aws_caller_identity` from `platform/infra/terraform/cluster/data.tf`
- `modules/hub-cluster/README.md` — Document all inputs, outputs, usage examples

**Files to Reference (source of extraction):**
- `platform/infra/terraform/cluster/main.tf` — EKS module call and VPC module call
- `platform/infra/terraform/cluster/locals.tf` — `local.azs`, `local.hub_cluster`, `local.vpc_cidr`, `local.ack_service_policies`. Remove hardcoded `peeks` from `context_prefix`; use `var.resource_prefix`
- `platform/infra/terraform/cluster/variables.tf` — Current variables `hub_vpc_id`, `hub_subnet_ids`, `workshop_participant_role_arn`, `clusters`, `identity_center_*`
- `platform/infra/terraform/cluster/data.tf` — Data sources for AZs, caller identity

**Key Changes:**
- `locals.tf` line `context_prefix = var.resource_prefix` — currently hardcoded to `"peeks"` via default; module should have no default prefix
- `variables.tf` line `variable "workshop_participant_role_arn"` — do NOT include in module; replace with generic `additional_access_entries`
- `variables.tf` line `variable "hub_vpc_id"` / `variable "hub_subnet_ids"` — replace with `create_vpc` toggle pattern

**Acceptance Criteria:**
- Module can create a hub EKS cluster with a new VPC
- Module can create a hub EKS cluster in an existing VPC
- Module exports all outputs needed by `modules/hub-bootstrap`
- `terraform validate` passes
- README documents all inputs/outputs

---

#### Task 1.2 — Create `modules/hub-bootstrap/` Module

**Doc Reference:** Section 3.1.2

**Description:**
This is the largest extraction. Pull the platform bootstrap logic from `platform/infra/terraform/common/` into a reusable module. This is the module customers will use to bootstrap their hub cluster with ArgoCD, secrets, IAM roles, and pod identity.

**Files to Create:**
- `modules/hub-bootstrap/main.tf` — Usage telemetry (optional), core bootstrap orchestration
- `modules/hub-bootstrap/argocd.tf` — Extracted from `platform/infra/terraform/common/argocd.tf`. Key change: remove `depends_on = [gitlab_personal_access_token.workshop]` from `kubernetes_secret.git_secrets`. Accept `var.git_config.credentials.token` instead of `local.gitlab_token`
- `modules/hub-bootstrap/secrets.tf` — Extracted from `platform/infra/terraform/common/secrets.tf`. Key change: make `git_token` in `aws_secretsmanager_secret_version.git_secret` come from `var.git_config.credentials.token` instead of `local.gitlab_token`. Make `keycloak` block conditional on `var.identity_config.provider == "keycloak"`
- `modules/hub-bootstrap/iam.tf` — Extracted from `platform/infra/terraform/common/iam.tf`. Parameterize role name prefixes with `var.resource_prefix`
- `modules/hub-bootstrap/pod-identity.tf` — Extracted from `platform/infra/terraform/common/pod-identity.tf`. Keep as-is, well-structured
- `modules/hub-bootstrap/variables.tf` — New variable structure (see Section 3.1.2 for full `git_config`, `identity_config`, `cicd_config` definitions). Also:
  - `hub_cluster_name` (string)
  - `hub_cluster_arn` (string)
  - `hub_cluster_oidc_issuer` (string)
  - `spoke_clusters` (map of cluster configs)
  - `resource_prefix` (string)
  - `hub_config` (any — the full parsed hub-config.yaml)
- `modules/hub-bootstrap/outputs.tf` — Export: `argocd_hub_role_arn`, `secrets_arns`, `ingress_endpoint`
- `modules/hub-bootstrap/locals.tf` — Extracted from `platform/infra/terraform/common/locals.tf`. Critical changes:
  - Line `gitops_addons_repo_url = local.gitlab_domain_name != "" ? "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url` → replace with `var.git_config.repo_url`
  - Same for `gitops_fleet_repo_url`, `gitops_workload_repo_url`, `gitops_platform_repo_url`
  - Remove `local.gitlab_domain_name`, `local.git_username` — these come from `var.git_config`
  - Remove `local.gitlab_token` — comes from `var.git_config.credentials.token`
  - Keep `local.addons`, `local.addons_metadata` structure but parameterize the metadata values
- `modules/hub-bootstrap/data.tf` — Extracted from `platform/infra/terraform/common/data.tf`
- `modules/hub-bootstrap/versions.tf`
- `modules/hub-bootstrap/README.md`

**Files NOT to include in module (stay in wrapper or move to workshop):**
- `gitlab.tf` — moves to `workshop/terraform/` (Task 4.2)
- `cloudfront.tf` — moves to `modules/ingress/` (Task 1.4)
- `ingress-nginx.tf` — moves to `modules/ingress/` (Task 1.4)
- `observability.tf` — moves to `modules/observability/` (Task 1.5)
- `ray-image-build.tf`, `ray-neuron-image-build.tf` — stay in wrapper, ML-specific
- `model-storage.tf`, `s3-csi-driver.tf` — stay in wrapper, ML-specific

**Acceptance Criteria:**
- Module bootstraps ArgoCD on a hub cluster without requiring GitLab
- Module accepts GitHub credentials and creates ArgoCD git secrets
- Module creates AWS Secrets Manager secrets with provider-agnostic structure
- `terraform validate` passes
- No references to `gitlab_personal_access_token` or `gitlab_domain_name`

---

#### Task 1.3 — Create `modules/ingress/` Module

**Doc Reference:** Section 3.1.3

**Description:**
Extract ingress infrastructure into a standalone module.

**Files to Create:**
- `modules/ingress/main.tf` — Ingress NGINX Helm release + optional CloudFront distribution
- `modules/ingress/cloudfront.tf` — Extracted from `platform/infra/terraform/common/cloudfront.tf`. Wrap in `count = var.create_cloudfront ? 1 : 0`
- `modules/ingress/variables.tf`:
  - `create_cloudfront` (bool, default `true`)
  - `custom_domain` (string, optional)
  - `certificate_arn` (string, optional — ACM cert for custom domain)
  - `ingress_type` (string: `"cloudfront"` | `"alb"` | `"nlb"` | `"custom"`)
  - `cluster_name` (string)
  - `resource_prefix` (string)
- `modules/ingress/outputs.tf` — Export: `ingress_endpoint`, `cloudfront_distribution_id` (optional)
- `modules/ingress/README.md`

**Files to Reference:**
- `platform/infra/terraform/common/cloudfront.tf` — Full CloudFront distribution with Keycloak-specific cache behavior
- `platform/infra/terraform/common/ingress-nginx.tf` — Helm release for ingress-nginx

**Acceptance Criteria:**
- Module deploys ingress-nginx + CloudFront when `create_cloudfront = true`
- Module deploys ingress-nginx only when `create_cloudfront = false`
- Customers can provide their own domain and ACM certificate
- `terraform validate` passes

---

#### Task 1.4 — Create `modules/observability/` Module

**Doc Reference:** Section 3.1.2 (observability.tf row)

**Description:**
Extract observability stack (Amazon Managed Grafana, Amazon Managed Prometheus) into a standalone module.

**Files to Create:**
- `modules/observability/main.tf` — Extracted from `platform/infra/terraform/common/observability.tf`
- `modules/observability/variables.tf` — `cluster_name`, `resource_prefix`, `enable_grafana`, `enable_prometheus`
- `modules/observability/outputs.tf` — `grafana_workspace_endpoint`, `grafana_workspace_id`, `prometheus_endpoint`
- `modules/observability/README.md`

**Acceptance Criteria:**
- Module creates Managed Grafana + Managed Prometheus
- Can be disabled entirely via variables
- `terraform validate` passes

---

#### Task 1.5 — Refactor `platform/infra/terraform/cluster/` as Thin Wrapper

**Doc Reference:** Section 3.1.4

**Description:**
Replace inline EKS resources in the cluster stack with a call to `modules/hub-cluster`. Remove spoke cluster creation entirely — spokes are now provisioned via CrossPlane/Kro (Epic 5).

**Files to Change:**
- `platform/infra/terraform/cluster/main.tf` — Replace EKS module calls with:
  ```hcl
  module "hub" {
    source = "../../../modules/hub-cluster"
    cluster_name       = local.hub_cluster.name
    kubernetes_version = local.hub_cluster.kubernetes_version
    region             = local.hub_cluster.region
    auto_mode          = local.hub_cluster.auto_mode
    resource_prefix    = var.resource_prefix
    create_vpc         = var.hub_vpc_id == "" ? true : false
    existing_vpc_id    = var.hub_vpc_id
    existing_subnet_ids = var.hub_subnet_ids
  }
  # No spoke clusters here — spokes are provisioned via CrossPlane/Kro from the hub
  ```
- `platform/infra/terraform/cluster/main.tf` — Remove all spoke cluster EKS module calls and `for_each` over `local.spoke_clusters`
- `platform/infra/terraform/cluster/locals.tf` — Remove `local.spoke_clusters` definition; simplify to hub-only
- `platform/infra/terraform/cluster/variables.tf` — Remove spoke-related variables; simplify to hub-only
- `platform/infra/terraform/cluster/outputs.tf` — Create/update to pass through hub module outputs only

**Acceptance Criteria:**
- `deploy.sh` creates only the hub cluster
- Spoke cluster Terraform code is fully removed
- Outputs are available for the common stack
- Spoke provisioning is documented as GitOps-only (link to Epic 5)

---

#### Task 1.6 — Refactor `platform/infra/terraform/common/` as Thin Wrapper

**Doc Reference:** Section 3.1.4

**Description:**
Replace inline resources in the common/bootstrap stack with calls to extracted modules.

**Files to Change:**
- `platform/infra/terraform/common/main.tf` — Add module calls to `hub-bootstrap`, `ingress`, `observability`
- `platform/infra/terraform/common/argocd.tf` — Replace with call to `modules/hub-bootstrap` (or keep as thin pass-through)
- `platform/infra/terraform/common/cloudfront.tf` — Replace with call to `modules/ingress`
- `platform/infra/terraform/common/ingress-nginx.tf` — Replace with call to `modules/ingress`
- `platform/infra/terraform/common/observability.tf` — Replace with call to `modules/observability`
- `platform/infra/terraform/common/locals.tf` — Simplify; most URL construction moves to module
- `platform/infra/terraform/common/outputs.tf` — Pass through module outputs

**Acceptance Criteria:**
- `deploy.sh` still works with no changes
- Platform bootstrap produces identical resources
- All secrets, IAM roles, and ArgoCD config are created correctly

---

#### Task 1.7 — Add Module Output Documentation

**Doc Reference:** Section 4.1 (Documentation table)

**Description:**
Write `README.md` for each module in `modules/` with full input/output tables, usage examples, and requirements.

**Files to Create/Update:**
- `modules/hub-cluster/README.md`
- `modules/hub-bootstrap/README.md`
- `modules/ingress/README.md`
- `modules/observability/README.md`

**Acceptance Criteria:**
- Each README has: description, requirements, inputs table, outputs table, usage example
- Examples show both local source and GitHub source with tag

---

#### Task 1.8 — Create `examples/` Directory with Consumption Examples

**Doc Reference:** Section 5 (Consumption Patterns)

**Description:**
Create working Terraform configurations that demonstrate each consumption pattern.

**Files to Create:**
- `examples/full-platform/main.tf` — Full deployment using all modules (Pattern 1, Section 5)
- `examples/full-platform/hub-config.yaml` — Example config with all addons
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

#### Task 2.1 — Extend `hub-config.yaml` Schema

**Doc Reference:** Section 3.2.1

**Description:**
Add new top-level sections to `hub-config.yaml` for provider configuration while maintaining backward compatibility.

**Files to Change:**
- `platform/infra/terraform/hub-config.yaml` — Add these new top-level keys:
  - `git:` block with `provider`, `url`, `revision`, `basepath` (currently these are under `repo:` — keep `repo:` for backward compat, add `git:` as the new canonical location)
  - `identity:` block with `provider` (keycloak|cognito|okta|external) and `config` map
  - `cicd:` block with `provider` (argo-workflows|gitlab-ci|github-actions|codepipeline)
  - `ingress:` block with `type` (cloudfront|alb|nlb|custom), `domain`, `certificate_arn`
  - Per-cluster: `existing_cluster` (bool), `existing_vpc_id` (string)

**Files to Update:**
- `platform/infra/terraform/common/variables.tf` — Add corresponding Terraform variable definitions that map to the new YAML keys
- `platform/infra/terraform/cluster/variables.tf` — Add `existing_cluster`, `existing_vpc_id` per cluster

**Acceptance Criteria:**
- Existing `hub-config.yaml` (without new keys) still works (backward compat via defaults)
- New keys are documented with comments in the YAML file
- Schema is documented in `docs/`

---

#### Task 2.2 — Refactor `utils.sh` to Remove Workshop Logic

**Doc Reference:** Section 3.2.2

**Description:**
Clean up the central utility script to remove workshop-specific concerns.

**File to Change:** `platform/infra/terraform/scripts/utils.sh`

**Specific Changes:**
- Line `export SKIP_GITLAB=${SKIP_GITLAB:-false}` — Remove. Git provider is determined from config
- Line `export WS_PARTICIPANT_ROLE_ARN=${WS_PARTICIPANT_ROLE_ARN:-""}` — Remove. Workshop-specific
- Line `export GIT_USERNAME=${GIT_USERNAME:-user1}` — Change default to empty string; derive from config
- Line `export USER1_PASSWORD=${USER1_PASSWORD:-${IDE_PASSWORD:-""}}` — Rename to `PLATFORM_ADMIN_PASSWORD`
- Line `export WORKSHOP_CLUSTERS=${WORKSHOP_CLUSTERS:-false}` — Remove entirely
- Lines 44-58 (the `if [[ "$WORKSHOP_CLUSTERS" == "true"` block) — Move to `workshop/scripts/utils.sh`
- Function `update_workshop_var()` (lines ~68-82) — Move to `workshop/scripts/utils.sh`
- Line `export CONFIG_FILE=${CONFIG_FILE:-"${GIT_ROOT_PATH}/platform/infra/terraform/hub-config.yaml"}` — Change to `export CONFIG_FILE=${CONFIG_FILE:-"./hub-config.yaml"}` (current directory, not repo-relative)

**Acceptance Criteria:**
- `utils.sh` has no references to `WORKSHOP_CLUSTERS`, `WS_PARTICIPANT_ROLE_ARN`, `update_workshop_var`
- `CONFIG_FILE` defaults to current directory
- Workshop functionality preserved in `workshop/scripts/utils.sh`

---

#### Task 2.3 — Refactor `cluster/deploy.sh`

**Doc Reference:** Section 3.2.3

**Description:**
Simplify the cluster deployment script.

**File to Change:** `platform/infra/terraform/cluster/deploy.sh`

**Specific Changes:**
- Remove `export WORKSHOP_CLUSTERS=${WORKSHOP_CLUSTERS:-false}` (line ~22)
- Remove workshop participant role ARN logic in `check_identity_center()` function
- Add config validation: check that `CONFIG_FILE` exists and has required `clusters` key
- Simplify environment variable setup — only require `CONFIG_FILE` and `AWS_REGION`

**Acceptance Criteria:**
- Script works with just `CONFIG_FILE` and `AWS_REGION` set
- No workshop-specific environment variables required
- Config validation fails gracefully with clear error messages

---

#### Task 2.4 — Refactor `common/deploy.sh`

**Doc Reference:** Section 3.2.3

**Description:**
Simplify the common/bootstrap deployment script.

**File to Change:** `platform/infra/terraform/common/deploy.sh`

**Specific Changes:**
- Remove `if ! $SKIP_GITLAB ; then` conditional block — derive from `git.provider` in config
- Remove `export WORKSHOP_CLUSTERS=${WORKSHOP_CLUSTERS:-false}` (line ~22)
- Add config validation for new `git`, `identity` sections
- Simplify: only require `CONFIG_FILE`, `AWS_REGION`, `PLATFORM_ADMIN_PASSWORD`

**Acceptance Criteria:**
- Script works without `SKIP_GITLAB` flag
- Git provider determined from config file
- No workshop-specific variables required

---

#### Task 2.5 — Refactor `locals.tf` in Common Stack

**Doc Reference:** Section 3.1.2 (locals.tf row), Section 1.2 (Repo URLs hardcoded)

**Description:**
This is a critical change. Remove all hardcoded GitLab URL construction from `locals.tf`.

**File to Change:** `platform/infra/terraform/common/locals.tf`

**Specific Line Changes:**
- Line `gitops_addons_repo_url = local.gitlab_domain_name != "" ? "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url` → Change to `gitops_addons_repo_url = var.git_config.repo_url`
- Line `gitops_fleet_repo_url = local.gitlab_domain_name != "" ? ...` → Same pattern: `var.git_config.repo_url`
- Line `gitops_workload_repo_url = local.gitlab_domain_name != "" ? ...` → Same
- Line `gitops_platform_repo_url = local.gitlab_domain_name != "" ? ...` → Same
- Line `gitlab_domain_name = var.gitlab_domain_name` → Remove or make conditional
- Line `git_username = var.git_username` → Change to `var.git_config.credentials.username`
- Line `keycloak_realm = "platform"` → Keep but make configurable via `var.identity_config`
- Line `backstage_image = var.backstage_image == "" ? "${data.aws_caller_identity.current.account_id}.dkr.ecr..." : var.backstage_image` → Keep, this is fine
- In `addons_metadata` map: lines referencing `gitlab_domain_name`, `git_username`, `working_repo`, `ide_password` → Replace with values from `var.git_config` and `var.identity_config`

**Acceptance Criteria:**
- No references to `gitlab_domain_name` in URL construction
- All repo URLs come from `var.git_config`
- `terraform plan` produces same resources when given equivalent config

---

#### Task 2.6 — Refactor `variables.tf` in Common Stack

**Doc Reference:** Section 3.1.2 (new variable structure)

**Description:**
Add new structured variable blocks and deprecate old individual variables.

**File to Change:** `platform/infra/terraform/common/variables.tf`

**Specific Changes:**
- Add `variable "git_config"` block (see Section 3.1.2 for full type definition)
- Add `variable "identity_config"` block
- Add `variable "cicd_config"` block
- Mark as deprecated (via description): `variable "gitlab_domain_name"`, `variable "git_username"`, `variable "git_password"`, `variable "working_repo"`
- Keep deprecated variables with defaults that fall back to `git_config` values for backward compatibility
- Rename `variable "ide_password"` to `variable "platform_admin_password"` (keep `ide_password` as deprecated alias)

**Acceptance Criteria:**
- New variable blocks are defined with proper types and defaults
- Old variables still work (backward compat) but are marked deprecated
- `terraform validate` passes

---

#### Task 2.7 — Create Config Validation Script

**Doc Reference:** Section 3.2.3

**Description:**
Create a script that validates `hub-config.yaml` before deployment.

**File to Create:** `platform/infra/terraform/scripts/validate-config.sh`

**Validation Rules:**
- Required keys: `clusters`, `clusters.hub`, `clusters.hub.name`, `clusters.hub.region`
- If `git.provider` is set, validate it's one of: `github`, `gitlab`, `codecommit`
- If `identity.provider` is set, validate it's one of: `keycloak`, `cognito`, `okta`, `external`
- If `ingress.type` is set, validate it's one of: `cloudfront`, `alb`, `nlb`, `custom`
- Warn if `enable_keycloak: true` but `identity.provider` is not `keycloak`
- Warn if `enable_gitlab: true` but `git.provider` is not `gitlab`

**Acceptance Criteria:**
- Script exits 0 on valid config, exits 1 on invalid
- Clear error messages for each validation failure
- Called by `deploy.sh` scripts before Terraform runs

---

#### Task 2.8 — Document External Config Usage

**Doc Reference:** Section 5 (Consumption Patterns)

**Description:**
Write a guide for customers on creating and using their own `hub-config.yaml`.

**File to Create:** `docs/HUB-CONFIG-GUIDE.md`

**Content:**
- Full schema reference for `hub-config.yaml`
- Example configs for: GitHub+Cognito, GitLab+Keycloak, GitHub+guest auth
- How to pass config to Terraform modules
- How to override specific values
- Migration guide from old `repo:` format to new `git:` format

**Acceptance Criteria:**
- Document covers all config keys with descriptions
- At least 3 example configs provided
- Reviewed by team

---

### EPIC 3: Decouple Keycloak-Backstage-GitLab

---

#### Task 3.1 — Decouple ArgoCD Bootstrap from GitLab

**Doc Reference:** Section 3.3.1

**Description:**
Remove the hard dependency on GitLab PAT in the ArgoCD bootstrap.

**File to Change:** `platform/infra/terraform/common/argocd.tf`

**Specific Line Changes:**
- `kubernetes_secret.git_secrets` resource:
  - Remove `depends_on = [gitlab_personal_access_token.workshop]`
  - Change `password = local.gitlab_token` → `password = var.git_config.credentials.token`
  - Change `url = "https://${local.gitlab_domain_name}/${local.git_username}"` → `url = var.git_config.repo_url` (derive base URL)
  - Change `url = "https://${local.gitlab_domain_name}/${local.git_username}/${var.working_repo}.git"` → construct from `var.git_config.repo_url`

**Also Change:** `platform/infra/terraform/common/providers.tf`
- Make the `gitlab` provider block conditional (only when `git.provider == "gitlab"`)
- Or move GitLab provider to `workshop/terraform/`

**Acceptance Criteria:**
- ArgoCD bootstrap works with GitHub PAT (no GitLab provider needed)
- ArgoCD bootstrap works with GitLab PAT (backward compat)
- No `gitlab_personal_access_token` references in `argocd.tf`

---

#### Task 3.2 — Make Keycloak Optional in Terraform

**Doc Reference:** Section 3.3.4

**Description:**
Conditionally create Keycloak-related resources based on identity provider config.

**Files to Change:**
- `platform/infra/terraform/common/secrets.tf`:
  - Wrap Keycloak password generation (`random_password.keycloak_admin`, `random_password.keycloak_postgres`) in `count = var.identity_config.provider == "keycloak" ? 1 : 0`
  - In `aws_secretsmanager_secret_version.git_secret`, make the `keycloak` block conditional:
    ```hcl
    keycloak = var.identity_config.provider == "keycloak" ? {
      admin_password    = local.keycloak_admin_password
      postgres_password = local.keycloak_postgres_password
    } : null
    ```
- `platform/infra/terraform/common/pod-identity.tf`:
  - Wrap Keycloak pod identity associations in conditional on `enable_keycloak`
- `platform/infra/terraform/common/iam.tf`:
  - Wrap Keycloak-specific IAM roles/policies in conditional

**Acceptance Criteria:**
- When `identity.provider != "keycloak"`, no Keycloak resources are created
- When `identity.provider == "keycloak"`, behavior is identical to current
- `terraform plan` shows no Keycloak resources when disabled

---

#### Task 3.3 — Make GitLab Optional in Terraform

**Doc Reference:** Section 3.3.1, Section 1.2 (GitLab deeply embedded)

**Description:**
Remove the requirement for the GitLab Terraform provider when using GitHub.

**Files to Change:**
- `platform/infra/terraform/common/providers.tf` — Make `provider "gitlab"` conditional or move to separate file that's only included for workshop
- `platform/infra/terraform/common/gitlab.tf` — This entire file should be conditional or moved to `workshop/`. Contains:
  - `data "gitlab_user" "workshop"` — workshop-specific
  - `resource "gitlab_personal_access_token" "workshop"` — workshop-specific
  - `locals { gitlab_token = ... }` — workshop-specific
- `platform/infra/terraform/common/versions.tf` — Make `gitlab` provider requirement conditional

**Acceptance Criteria:**
- `terraform init` succeeds without GitLab provider when `git.provider == "github"`
- No GitLab data sources or resources created when using GitHub
- Workshop path still works with GitLab

---

#### Task 3.4 — Refactor Backstage Helm Chart for Multi-Auth

**Doc Reference:** Section 3.3.2

**Description:**
Update the Backstage Helm chart to support multiple authentication providers.

**Files to Change:**
- `gitops/addons/charts/backstage/values.yaml` — Add:
  ```yaml
  auth:
    provider: keycloak  # keycloak | cognito | github | guest
  ```
- `gitops/addons/charts/backstage/templates/install.yaml` (or equivalent config template) — Template the auth section:
  ```yaml
  {{- if eq .Values.auth.provider "keycloak" }}
  # Keycloak OIDC config with sync waves 10→15→25
  {{- else if eq .Values.auth.provider "cognito" }}
  # Cognito OIDC config
  {{- else if eq .Values.auth.provider "guest" }}
  # Guest auth (no external IdP)
  {{- end }}
  ```
- `gitops/addons/charts/backstage/templates/keycloak-config.yaml` — Wrap in `{{- if eq .Values.auth.provider "keycloak" }}`
- `gitops/addons/charts/backstage/templates/external-secret.yaml` — Make Keycloak secret sync conditional

**Also Update:**
- `gitops/addons/bootstrap/default/addons.yaml` — Add `auth_provider: keycloak` default
- `gitops/addons/environments/control-plane/addons.yaml` — Add `auth_provider` override capability

**Acceptance Criteria:**
- Backstage deploys with Keycloak auth (current behavior, backward compat)
- Backstage deploys with guest auth (no Keycloak dependency)
- Backstage deploys with Cognito auth (new capability)
- No Keycloak sync waves when `auth.provider != "keycloak"`

---

#### Task 3.5 — Refactor Backstage Helm Chart for Multi-Git

**Doc Reference:** Section 3.3.3

**Description:**
Update the Backstage Helm chart to support multiple Git providers.

**Files to Change:**
- `gitops/addons/charts/backstage/values.yaml` — Add:
  ```yaml
  git:
    provider: gitlab  # gitlab | github | codecommit
  ```
- `gitops/addons/charts/backstage/templates/install.yaml` — Template the `integrations:` section of `app-config.yaml`:
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
- `backstage/app-config.yaml` — Update the base config to use environment variable substitution that works for both providers

**Acceptance Criteria:**
- Backstage integrates with GitLab when `git.provider: gitlab`
- Backstage integrates with GitHub when `git.provider: github`
- Catalog discovery works with both providers

---

#### Task 3.6 — Update Backstage Templates for Multi-Git

**Doc Reference:** Section 3.3.3

**Description:**
Update Backstage software templates to support publishing to multiple Git providers.

**Files to Change:**
- All template YAML files in `platform/backstage/templates/` that have `publish:gitlab` steps — Add conditional:
  ```yaml
  steps:
    - id: publish
      name: Publish
      action: "publish:{{ .Values.git.provider }}"  # publish:gitlab or publish:github
  ```
- Specifically check and update:
  - `platform/backstage/templates/*/template.yaml` — Each template's publish step
  - `platform/backstage/customtemplates/*/template.yaml` — Custom templates

**Acceptance Criteria:**
- Templates publish to GitLab when `git.provider: gitlab`
- Templates publish to GitHub when `git.provider: github`
- Template parameters adapt to the Git provider (e.g., "GitLab Group" vs "GitHub Org")

---

#### Task 3.7 — Refactor `secrets.tf` for Provider-Agnostic Secrets

**Doc Reference:** Section 3.3.1, Section 1.2 (Secrets assume workshop topology)

**Description:**
Refactor secrets to not assume GitLab or Keycloak.

**File to Change:** `platform/infra/terraform/common/secrets.tf`

**Specific Changes:**
- `aws_secretsmanager_secret_version.git_secret` — Change the `secret_string` structure:
  - `git_token = local.gitlab_token` → `git_token = var.git_config.credentials.token`
  - `git_username = var.git_username` → `git_username = var.git_config.credentials.username`
  - `keycloak` block → conditional (see Task 3.2)
  - `user_password = var.ide_password` → `user_password = var.platform_admin_password`
  - `user_password_hash` → conditional on identity provider
- `aws_secretsmanager_secret_version.cluster_config` — The `metadata` block references `addons_metadata` which contains `gitlab_domain_name`, `git_username`, `working_repo` — these must come from `var.git_config`

**Acceptance Criteria:**
- Secrets created with GitHub token when using GitHub
- Secrets created without Keycloak block when Keycloak is disabled
- No references to `local.gitlab_token` or `var.ide_password`

---

#### Task 3.8 — Update Keycloak Chart for Optional Deployment

**Doc Reference:** Section 3.3.4

**Description:**
Ensure the Keycloak addon chart cleanly handles being disabled.

**Files to Change:**
- `gitops/addons/charts/keycloak/templates/*.yaml` — Verify all templates are wrapped in `{{- if .Values.enable_keycloak }}`
- `gitops/addons/charts/application-sets/templates/*.yaml` — Verify the Keycloak ApplicationSet is conditional on `enable_keycloak` label
- Check for any hardcoded references to Keycloak namespace or services in other charts (backstage, argo-workflows, kargo)

**Acceptance Criteria:**
- `enable_keycloak: false` results in zero Keycloak resources
- No other chart fails when Keycloak is absent
- ArgoCD sync completes cleanly without Keycloak

---

#### Task 3.9 — Update GitLab Chart for Optional Deployment

**Doc Reference:** Section 3.3.1

**Description:**
Ensure the GitLab addon chart cleanly handles being disabled.

**Files to Change:**
- `gitops/addons/charts/gitlab/templates/*.yaml` — Verify all templates are wrapped in `{{- if .Values.enable_gitlab }}`
- Check for references to GitLab hostname in other charts (backstage, argo-workflows)

**Acceptance Criteria:**
- `enable_gitlab: false` results in zero GitLab resources
- No other chart has dangling references to GitLab
- ArgoCD sync completes cleanly without GitLab

---

#### Task 3.10 — Test Standalone Backstage (Guest Auth + GitHub)

**Doc Reference:** Section 3.3.2, Section 3.3.3

**Description:**
End-to-end validation that Backstage works without Keycloak and without GitLab.

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
  provider: guest  # or external
```

**Test Steps:**
1. Deploy hub cluster with above config
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
Set up the workshop-specific directory structure in the internal `platform-engineering-on-eks` GitLab repo to host all workshop code that is being removed from `appmod-blueprints`.

**Files to Create (in `platform-engineering-on-eks` repo):**
- `terraform/main.tf` — Sources modules from `appmod-blueprints` via GitHub tag
- `terraform/variables.tf` — Workshop-specific variables
- `scripts/` — Directory for workshop-specific scripts
- `hub-config.yaml` — Placeholder (populated in Task 4.5)
- `README.md` — Workshop deployment guide

**Acceptance Criteria:**
- Directory structure matches Section 3.4.2 layout
- `terraform/main.tf` references `appmod-blueprints` modules via `?ref=<tag>`
- README explains the workshop deployment flow and relationship to `appmod-blueprints`

---

#### Task 4.2 — Move `gitlab.tf` to `platform-engineering-on-eks` Repo

**Doc Reference:** Section 3.4.1 (Files to Move table, row 1)

**Description:**
Move GitLab PAT creation from `appmod-blueprints` to the workshop repo. Delete it from the solution repo.

**File to Move:** `platform/infra/terraform/common/gitlab.tf` → `platform-engineering-on-eks` repo `terraform/gitlab.tf`

**Changes in `appmod-blueprints`:**
- Delete `platform/infra/terraform/common/gitlab.tf`
- Remove `provider "gitlab"` from `platform/infra/terraform/common/providers.tf` (or make conditional per Task 3.3)
- Remove `gitlab` provider from `platform/infra/terraform/common/versions.tf` required_providers

**Changes in `platform-engineering-on-eks`:**
- `terraform/gitlab.tf` — Contains `data "gitlab_user"`, `resource "gitlab_personal_access_token"`, `locals { gitlab_token }`
- `terraform/providers.tf` — Create with `provider "gitlab"` block
- `terraform/versions.tf` — Create with GitLab provider version requirement
- `terraform/outputs.tf` — Export `gitlab_token` for use by the bootstrap module

**Acceptance Criteria:**
- `platform/infra/terraform/common/gitlab.tf` no longer exists in `appmod-blueprints`
- Workshop repo creates GitLab PAT independently
- Workshop repo passes token to `appmod-blueprints` bootstrap module as input variable

---

#### Task 4.3 — Move Workshop Scripts to `platform-engineering-on-eks` Repo

**Doc Reference:** Section 3.4.1 (Files to Move table, rows 2-4)

**Files to Move from `appmod-blueprints` to `platform-engineering-on-eks`:**
- `platform/infra/terraform/scripts/2-gitlab-init.sh` → `platform-engineering-on-eks/scripts/gitlab-init.sh`
- `platform/infra/terraform/scripts/check-workshop-setup.sh` → `platform-engineering-on-eks/scripts/check-setup.sh`
- Workshop-specific functions from `platform/infra/terraform/scripts/utils.sh` → `platform-engineering-on-eks/scripts/utils.sh`:
  - `WORKSHOP_CLUSTERS` logic block (lines ~44-58 of current `utils.sh`)
  - `update_workshop_var()` function (lines ~68-82)
  - `WS_PARTICIPANT_ROLE_ARN` export

**Changes in `appmod-blueprints`:**
- Delete `platform/infra/terraform/scripts/2-gitlab-init.sh`
- Delete `platform/infra/terraform/scripts/check-workshop-setup.sh`
- Remove workshop functions from `platform/infra/terraform/scripts/utils.sh` (per Task 2.2)

**Acceptance Criteria:**
- No workshop-specific code remains in `appmod-blueprints/platform/infra/terraform/scripts/`
- Workshop scripts work when called from `platform-engineering-on-eks` repo
- `platform-engineering-on-eks/scripts/utils.sh` can source the cleaned-up `utils.sh` from `appmod-blueprints` and add workshop overrides

---

#### Task 4.4 — Create Workshop `deploy.sh` Orchestrator in `platform-engineering-on-eks`

**Doc Reference:** Section 3.4.2

**Description:**
Create a single deployment script in the workshop repo that orchestrates all steps, consuming `appmod-blueprints` as upstream.

**File to Create:** `platform-engineering-on-eks/deploy.sh`

**Script Flow:**
1. Source `scripts/utils.sh` (workshop-specific)
2. Validate prerequisites (AWS CLI, kubectl, terraform, yq)
3. Run `terraform/` to create GitLab PAT and workshop-specific resources
4. Export GitLab token as env var
5. Run Terraform that sources `appmod-blueprints` modules for cluster creation
6. Run Terraform that sources `appmod-blueprints` modules for bootstrap (passing GitLab token)
7. Run initialization scripts
8. Run `scripts/gitlab-init.sh`
9. Print URLs

**Also Create:** `platform-engineering-on-eks/destroy.sh` — Reverse order teardown

**Acceptance Criteria:**
- `deploy.sh` deploys the full workshop from scratch
- `destroy.sh` cleanly tears down everything
- Workshop deployment is identical to current behavior
- All `appmod-blueprints` references use versioned tags

---

#### Task 4.5 — Create Workshop `hub-config.yaml` in `platform-engineering-on-eks`

**Doc Reference:** Section 3.4.2, Section 3.2.1

**Description:**
Create a workshop-specific config in the workshop repo.

**File to Create:** `platform-engineering-on-eks/hub-config.yaml`

**Content:** Based on current `appmod-blueprints/platform/infra/terraform/hub-config.yaml` with additions:
```yaml
git:
  provider: gitlab
identity:
  provider: keycloak
cicd:
  provider: argo-workflows
ingress:
  type: cloudfront
```
- Keep `resource_prefix: peeks`
- Keep all addons enabled (keycloak, backstage, gitlab, etc.)
- Keep `domain_name: cnoe.io`

**Acceptance Criteria:**
- Workshop config is self-contained in the workshop repo
- Workshop config includes all new schema keys from Section 3.2.1
- Backward compatible with current deployment

---

#### Task 4.6 — Validate Workshop End-to-End from `platform-engineering-on-eks`

**Doc Reference:** Section 4.2 (Risks table, row 1)

**Description:**
Full end-to-end deployment test of the workshop path from the `platform-engineering-on-eks` repo after all refactoring.

**Test Steps:**
1. Start from clean AWS account
2. Clone `platform-engineering-on-eks` repo
3. Run `deploy.sh` (which sources `appmod-blueprints` modules)
4. Verify all clusters created (hub, spoke-dev, spoke-prod)
5. Verify ArgoCD is running and syncing
6. Verify Keycloak is running with test users
7. Verify GitLab is running with workshop repo
8. Verify Backstage is running with all templates
9. Verify Argo Workflows, Kargo, Kro are functional
10. Run `destroy.sh`
11. Verify clean teardown

**Acceptance Criteria:**
- All 11 steps pass
- No regressions from current workshop behavior
- Deployment time is within 10% of current
- `appmod-blueprints` repo has zero workshop-specific code

---

#### Task 4.7 — Document Workshop Repo Relationship

**Doc Reference:** Section 3.4

**Description:**
Document how `platform-engineering-on-eks` consumes `appmod-blueprints` as upstream.

**Files to Create:**
- `platform-engineering-on-eks/docs/UPSTREAM-RELATIONSHIP.md` — How the workshop repo depends on `appmod-blueprints`, how to update when upstream releases a new version
- `appmod-blueprints/docs/WORKSHOP-SEPARATION.md` — Brief note explaining that workshop code lives in the internal `platform-engineering-on-eks` repo, with link

**Content:**
- Version pinning strategy (which `appmod-blueprints` tag the workshop uses)
- How to update the workshop when `appmod-blueprints` releases a new version
- What lives where (clear boundary definition)
- How to test compatibility between the two repos

**Acceptance Criteria:**
- Relationship is clearly documented in both repos
- Update/sync process is defined
- Team understands the boundary

---

### EPIC 5: GitOps Spoke Management (CrossPlane/Kro)

---

#### Task 5.1 — Enhance `kro-clusters` Chart for Full Spoke Lifecycle

**Doc Reference:** Section 3.5.3

**Description:**
Extend the existing `kro-clusters` Helm chart to support creating, bootstrapping, and destroying spoke clusters entirely through GitOps.

**Files to Change:**
- `gitops/addons/charts/kro-clusters/` — Add new Kro ResourceGraphDefinitions:
  - `spoke-cluster-rgd.yaml` — RGD that creates an EKS cluster via ACK EKS controller
  - `spoke-bootstrap-rgd.yaml` — RGD that creates ArgoCD cluster secret + External Secrets for the spoke
  - `spoke-destroy-rgd.yaml` — RGD that cleanly removes a spoke
- `gitops/fleet/kro-values/` — Add default values for spoke cluster RGDs

**Acceptance Criteria:**
- Kro RGD can create a new EKS spoke cluster
- Kro RGD can bootstrap a spoke with ArgoCD registration
- Kro RGD can destroy a spoke cleanly
- All RGDs are deployed via ArgoCD ApplicationSet

---

#### Task 5.2 — Add Spoke Registration via Kro ResourceGroup

**Doc Reference:** Section 3.5.2

**Description:**
Create a Kro RGD specifically for registering an existing cluster as a spoke (no cluster creation).

**Files to Create:**
- `gitops/addons/charts/kro/resource-groups/spoke-registration/` — New RGD directory
  - `rgd.yaml` — ResourceGraphDefinition that:
    - Creates ArgoCD cluster secret with spoke cluster credentials
    - Creates External Secrets store for the spoke
    - Triggers ArgoCD ApplicationSet to bootstrap addons on the spoke
  - `instance-example.yaml` — Example ResourceGroup instance

**Acceptance Criteria:**
- Applying a ResourceGroup instance registers an existing cluster
- ArgoCD auto-discovers the new spoke and syncs addons
- Spoke addons are determined by labels on the cluster secret

---

#### Task 5.3 — Create "Add Spoke Cluster" Backstage Template

**Doc Reference:** Section 3.5.2

**Description:**
Self-service Backstage template for spoke cluster provisioning.

**Files to Create:**
- `platform/backstage/templates/spoke-cluster/template.yaml` — Backstage template that:
  - Collects: cluster name, region, environment (dev/prod/staging), addon selections
  - Creates a Kro ResourceGroup instance (via `kro:create` action or kubectl apply)
  - Registers the spoke in the Backstage catalog

**Acceptance Criteria:**
- Template appears in Backstage catalog
- User can fill in parameters and create a spoke
- Spoke cluster is provisioned and bootstrapped automatically

---

#### Task 5.4 — Remove Spoke Creation from Terraform Cluster Stack

**Doc Reference:** Section 3.5.3

**Description:**
Remove all spoke cluster Terraform code from the cluster stack. The cluster stack becomes hub-only. Spokes are exclusively provisioned via CrossPlane/Kro.

**Files to Change:**
- `platform/infra/terraform/cluster/main.tf` — Remove all `for_each` loops over `local.spoke_clusters` and spoke EKS module calls
- `platform/infra/terraform/cluster/locals.tf` — Remove `local.spoke_clusters` definition
- `platform/infra/terraform/cluster/variables.tf` — Remove spoke-related entries from the `clusters` variable type (or keep the type but only process hub)
- `platform/infra/terraform/cluster/data.tf` — Remove spoke-related data sources
- `platform/infra/terraform/cluster/deploy.sh` — Remove spoke cluster iteration; only deploy hub

**State Migration Note:**
Existing deployments that have spoke clusters in Terraform state will need a migration path:
1. `terraform state rm` spoke resources from the cluster state
2. Import spoke clusters into CrossPlane/Kro management
3. Document this in `docs/MIGRATION-GUIDE.md`

**Acceptance Criteria:**
- Cluster stack creates only the hub cluster
- No spoke-related Terraform code remains
- `terraform plan` shows no spoke resources
- Migration path documented for existing deployments

---

#### Task 5.5 — Document GitOps Spoke Provisioning

**Doc Reference:** Section 3.5

**File to Create:** `docs/GITOPS-SPOKE-PROVISIONING.md`

**Content:**
- How spoke provisioning works via Kro/CrossPlane
- Step-by-step guide to add a spoke via Backstage
- Step-by-step guide to add a spoke via kubectl (Kro ResourceGroup)
- How ArgoCD auto-discovers and bootstraps spokes
- Comparison: Terraform spokes vs GitOps spokes

**Acceptance Criteria:**
- Document covers both Backstage and kubectl paths
- Includes architecture diagram
- Reviewed by team

---

#### Task 5.6 — Test Full GitOps Spoke Lifecycle

**Doc Reference:** Section 3.5.2

**Description:**
Validate the full GitOps spoke lifecycle: hub created by Terraform, spokes created and managed entirely by Kro/CrossPlane.

**Test Steps:**
1. Deploy hub cluster via Terraform (hub-only, no spokes in TF)
2. Verify CrossPlane and Kro are running on hub
3. Create a spoke cluster via Kro ResourceGroup instance (kubectl apply)
4. Verify EKS spoke cluster is created by CrossPlane/ACK
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

**Description:**
Define versioning strategy and create initial release.

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
- Customers can reference `?ref=v1.0.0` in module source

---

#### Task 6.2 — Add GitHub Actions for Module Validation

**Doc Reference:** Section 4.2 (Risks table)

**File to Create:** `.github/workflows/terraform-validate.yml`

**Pipeline Steps:**
- `terraform fmt -check -recursive` on `modules/`
- `terraform validate` on each module
- `tfsec` scan on `modules/`
- `checkov` scan on `modules/`
- Run on: push to `main`, PRs targeting `main`

**Acceptance Criteria:**
- CI runs on every PR
- All modules pass fmt, validate, tfsec
- Failed checks block merge

---

#### Task 6.3 — Add Integration Test for External Consumption

**Doc Reference:** Section 5 (Consumption Patterns)

**File to Create:** `.github/workflows/integration-test.yml`

**Test:**
- Create a temporary Terraform config that sources modules from the repo
- Run `terraform init` and `terraform validate`
- Verify modules can be sourced with `?ref=<tag>`
- Run on: release creation

**Acceptance Criteria:**
- Integration test passes on every release
- Simulates real customer consumption pattern
- Tests at least 2 consumption patterns (hub-only, full-platform)

---

#### Task 6.4 — Create CHANGELOG.md

**Doc Reference:** Section 3.6

**File to Create:** `CHANGELOG.md`

**Format:** Keep a Changelog format (https://keepachangelog.com/)

**Acceptance Criteria:**
- CHANGELOG exists with initial `v1.0.0` entry
- Updated with every release
- Documents breaking changes prominently

---

#### Task 6.5 — Document Module Pinning for Customers

**Doc Reference:** Section 3.6.1, Section 3.6.2

**File to Create:** Section in `docs/CONSUMPTION-GUIDE.md` (or standalone `docs/VERSION-PINNING.md`)

**Content:**
- How to pin Terraform modules to a version tag
- How to pin ArgoCD `targetRevision` to a version tag
- How to upgrade between versions
- Breaking change policy

**Acceptance Criteria:**
- Clear examples for both Terraform and ArgoCD pinning
- Upgrade path documented

---

### EPIC 7: Documentation

---

#### Task 7.1 — Create `docs/CONSUMPTION-GUIDE.md`

**Doc Reference:** Section 5

**Description:**
Comprehensive guide for external consumption of the solution.

**Content Sections:**
1. Prerequisites (AWS account, tools, permissions)
2. Pattern 1: Full Platform deployment (Section 5, Pattern 1)
3. Pattern 2: Hub Only on Existing Cluster (Section 5, Pattern 2)
4. Pattern 3: GitOps Only / Bring Your Own Cluster (Section 5, Pattern 3)
5. Pattern 4: Cherry-Pick Individual Addons (Section 5, Pattern 4)
6. Configuration reference (link to HUB-CONFIG-GUIDE.md)
7. Troubleshooting

**Acceptance Criteria:**
- Each pattern has step-by-step instructions
- Each pattern has a working example config
- Tested by someone unfamiliar with the repo

---

#### Task 7.2 — Create `docs/MODULE-REFERENCE.md`

**Doc Reference:** Section 4.1

**Description:**
Full reference documentation for all Terraform modules.

**Content per Module:**
- Description and purpose
- Requirements (providers, Terraform version)
- Inputs table (name, type, default, required, description)
- Outputs table (name, description)
- Usage example (local source and GitHub source)
- Dependencies on other modules

**Modules to Document:**
- `modules/hub-cluster`
- `modules/hub-bootstrap`
- `modules/ingress`
- `modules/observability`

**Acceptance Criteria:**
- All modules documented
- Auto-generated where possible (terraform-docs)
- Examples are copy-pasteable

---

#### Task 7.3 — Create `docs/MIGRATION-GUIDE.md`

**Doc Reference:** Section 4.1 (Documentation table)

**Description:**
Guide for existing users (who forked the repo) to migrate to module-based consumption.

**Content:**
1. What changed and why
2. Step-by-step migration from fork to module source
3. How to preserve existing state
4. How to handle custom modifications
5. Breaking changes and workarounds

**Acceptance Criteria:**
- Covers the most common fork-based usage patterns
- State migration steps are tested
- Reviewed by someone who has forked the repo

---

#### Task 7.4 — Update Root `README.md`

**Doc Reference:** Section 4.1

**Description:**
Update the main README to reflect the new modular architecture.

**File to Change:** `README.md` (root of appmod-blueprints)

**Changes:**
- Add "Quick Start" section with 3 consumption patterns
- Add "For Customers" section linking to CONSUMPTION-GUIDE.md
- Add "For Workshop" section linking to workshop/README.md
- Update architecture diagram to show module boundaries
- Add version badge

**Acceptance Criteria:**
- README clearly communicates the two paths (solution vs workshop)
- Links to all relevant guides
- First-time visitor understands how to consume the solution

---

#### Task 7.5 — Document Current Terraform Split

**Doc Reference:** Section 1.3

**Description:**
Document the existing cluster/common split before making changes. This is the first task to execute.

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
- `docs/ADR-001-workshop-separation.md` — Workshop isolation to `platform-engineering-on-eks` repo (also Task 4.7)
- `docs/ADR-002-module-structure.md` — Why these specific modules, what goes where
- `docs/ADR-003-provider-abstraction.md` — How Git/Identity/CICD providers are abstracted
- `docs/ADR-004-hub-config-schema.md` — Hub config schema design decisions

**Acceptance Criteria:**
- Each ADR follows standard format (Context, Decision, Consequences)
- Decisions are reviewed and approved by team
- ADRs are referenced from relevant code/docs

---

### EPIC 8: Agent Platform Extension

> **Reference**: The agent platform design is fully documented in [`docs/agent-platform/DESIGN.md`](./agent-platform/DESIGN.md). This epic implements that design on top of the modular architecture established by Epics 1–7. The DESIGN.md itself requires updates to align with the upgrade approach — see Tasks 8.1 and 8.2.

> **Key Conflict**: The current DESIGN.md assumes the pre-upgrade tightly-coupled architecture (hardcoded GitLab URLs, `workshop_type` Terraform variable, Keycloak dependency in Agent Gateway auth). These assumptions must be reconciled with the modular, provider-agnostic architecture before implementation begins.

---

#### Task 8.1 — Update `docs/agent-platform/DESIGN.md` to Align with Modular Architecture

**Doc Reference:** Section 2.1 (Design Principles), DESIGN.md Sections 2–6

**Description:**
The current DESIGN.md was written against the pre-upgrade tightly-coupled architecture. It contains several assumptions that conflict with the upgrade approach. This task updates the design document to align with the modular, provider-agnostic architecture.

**File to Change:** `docs/agent-platform/DESIGN.md`

**Specific Conflicts to Resolve:**

1. **`workshop_type` Terraform variable** (DESIGN.md Section 4, Level 3):
   - DESIGN.md adds `variable "workshop_type"` with values `platform-engineering` | `agent-platform` to `platform/infra/terraform/variables.tf`
   - **Conflict**: The upgrade approach (Section 3.4) moves all workshop-specific code to the `platform-engineering-on-eks` GitLab repo. `workshop_type` is a workshop concern, not a solution concern.
   - **Resolution**: Remove `workshop_type` from `appmod-blueprints`. The agent platform feature flag should be `enable_agent_platform` only (a solution-level toggle), driven by `hub-config.yaml` addons section (`agent-platform.enabled: true`). The `workshop_type` variable moves to `platform-engineering-on-eks` repo where it controls which workshop variant to deploy.

2. **CloudFormation parameter for `WorkshopType`** (DESIGN.md Section 4, Level 3):
   - DESIGN.md includes a CloudFormation `Parameters` block with `WorkshopType`
   - **Conflict**: CloudFormation is workshop infrastructure (AWS Workshop Studio). This belongs in `platform-engineering-on-eks`, not `appmod-blueprints`.
   - **Resolution**: Remove CloudFormation references from DESIGN.md. Add a note that workshop-specific deployment orchestration lives in the `platform-engineering-on-eks` repo.

3. **`WORKSHOP_TYPE` environment variable in bootstrap script** (DESIGN.md Section 4, Level 4):
   - DESIGN.md references `platform/infra/terraform/scripts/bootstrap.sh` with `WORKSHOP_TYPE` env var
   - **Conflict**: Per Task 2.2, `utils.sh` is being cleaned of workshop logic. `WORKSHOP_TYPE` is a workshop concern.
   - **Resolution**: Replace with `ENABLE_AGENT_PLATFORM` env var only. The bootstrap script in `appmod-blueprints` should only know about `enable_agent_platform`, not workshop types.

4. **Agent Gateway auth assumes Keycloak** (DESIGN.md Section 3, Agent Gateway config):
   - Agent Gateway config has `auth.type: jwt` with `jwksUrl` pointing to Keycloak
   - **Conflict**: Per Epic 3, Keycloak is optional. Identity provider is configurable.
   - **Resolution**: Agent Gateway auth should use `identity.provider` from `hub-config.yaml`. Template the JWKS URL based on the configured identity provider (Keycloak, Cognito, external).

5. **Hardcoded `peeks` resource prefix** (DESIGN.md throughout):
   - ArgoCD application names use `peeks-agent-platform-*` prefix
   - **Conflict**: Per Task 1.1, `resource_prefix` is parameterized (no hardcoded `peeks`).
   - **Resolution**: Use `{{ .Values.global.resourcePrefix }}` consistently. Update all examples to show parameterized prefix.

6. **Spoke cluster deployment assumes Terraform-created spokes** (DESIGN.md Architecture Overview):
   - DESIGN.md shows components deploying to "Spoke Clusters (Dev/Prod)" without specifying how spokes are created
   - **Conflict**: Per Epic 5, spokes are exclusively provisioned via CrossPlane/Kro.
   - **Resolution**: Add a note that spoke clusters are provisioned via GitOps (CrossPlane/Kro) and agent platform components deploy to spokes that are registered via Kro ResourceGroup instances.

7. **Feature flag at `gitops/addons/bootstrap/default/addons.yaml`** (DESIGN.md Section 4, Level 1):
   - This is correct and aligns with the upgrade approach. No change needed.
   - **Confirm**: The `agent-platform.enabled` flag in `addons.yaml` is the primary mechanism. This is consistent with how all other addons work.

8. **Bridge chart references `sample-agent-platform-on-eks` repo** (DESIGN.md Section 2):
   - The bridge chart at `gitops/addons/charts/agent-platform/` references an external repo for component charts
   - **Alignment**: This is good — it follows the separation of concerns principle. No conflict.
   - **Enhancement**: The bridge chart `values.yaml` should use `git.provider` and `git.url` from `hub-config.yaml` for the external repo URL, rather than hardcoding `https://github.com/aws-samples/sample-agent-platform-on-eks`.

**Also Update:** `docs/agent-platform/README.md`
- Remove `terraform apply -var="workshop_type=agent-platform"` from Quick Start
- Replace with `terraform apply -var="enable_agent_platform=true"` or hub-config approach
- Update "Disable Agent Platform" section to remove `workshop_type` references

**Acceptance Criteria:**
- DESIGN.md has zero references to `workshop_type` or `WorkshopType`
- DESIGN.md has zero CloudFormation references (those belong in workshop repo)
- Agent Gateway auth is templated for multiple identity providers
- Resource prefix is parameterized throughout
- Spoke cluster provisioning references GitOps (CrossPlane/Kro)
- Feature flag mechanism uses `hub-config.yaml` addons + `enable_agent_platform` TF variable only
- README.md Quick Start uses the modular approach

---

#### Task 8.2 — Update `docs/agent-platform/COMPONENTS.md` and `TROUBLESHOOTING.md` for Modular Architecture

**Doc Reference:** DESIGN.md Sections 3, 8, 9

**Description:**
Update supporting agent platform docs to align with the modular architecture.

**Files to Change:**
- `docs/agent-platform/COMPONENTS.md`:
  - Update IAM role references to use parameterized `resource_prefix` instead of hardcoded account IDs
  - Update service account annotations to reference `modules/hub-bootstrap` outputs for IAM role ARNs
  - Add note that Tofu Controller IAM role is created by `modules/hub-bootstrap` (not manually)
- `docs/agent-platform/TROUBLESHOOTING.md` (if it exists):
  - Update troubleshooting steps to reference the modular deployment path
  - Remove references to `workshop_type` variable

**Acceptance Criteria:**
- No hardcoded account IDs or role ARNs in examples
- IAM roles reference module outputs
- Troubleshooting uses modular deployment commands

---

#### Task 8.3 — Add `enable_agent_platform` to `hub-config.yaml` Schema

**Doc Reference:** Section 3.2.1 (Extend hub-config schema), DESIGN.md Section 4

**Description:**
Add the agent platform feature flag to the `hub-config.yaml` schema as part of the addons section. This is the primary mechanism for enabling/disabling the agent platform.

**Files to Change:**
- `platform/infra/terraform/hub-config.yaml` — Add to hub cluster addons:
  ```yaml
  clusters:
    hub:
      addons:
        # ... existing addons ...
        enable_agent_platform: false  # NEW: Agent platform feature flag
  ```
- `platform/infra/terraform/common/variables.tf` — Add:
  ```hcl
  variable "enable_agent_platform" {
    description = "Enable agent platform components (Kagent, LiteLLM, Agent Gateway, Langfuse, Jaeger, Tofu Controller, Agent Core)"
    type        = bool
    default     = false
  }
  ```
- `platform/infra/terraform/common/locals.tf` — Add `enable_agent_platform` to `addons_metadata` map so it flows through to ArgoCD bootstrap as a label/annotation that the bridge chart can read

**Acceptance Criteria:**
- `enable_agent_platform: false` in hub-config results in no agent platform resources
- `enable_agent_platform: true` triggers the bridge chart to create ArgoCD Applications
- Flag flows through Terraform → ArgoCD bootstrap → bridge chart conditional
- Backward compatible (missing key defaults to `false`)

---

#### Task 8.4 — Create Agent Platform Bridge Chart

**Doc Reference:** DESIGN.md Section 2 (Repository Changes), DESIGN.md Section 4 (Feature Flag)

**Description:**
Implement the bridge chart as described in DESIGN.md. This is the lightweight Helm chart in `appmod-blueprints` that creates individual ArgoCD Applications pointing to component charts in the `sample-agent-platform-on-eks` repository.

**Files to Create:**
- `gitops/addons/charts/agent-platform/Chart.yaml` — Standard chart metadata
- `gitops/addons/charts/agent-platform/values.yaml` — Default values (see DESIGN.md Section 6, "Bridge Chart Default" for full structure):
  ```yaml
  enabled: false
  externalRepo:
    url: "https://github.com/aws-samples/sample-agent-platform-on-eks"
    revision: "main"
    basePath: "gitops/"
  global:
    namespace: "agent-platform"
    resourcePrefix: ""  # Parameterized, not hardcoded
    awsRegion: "us-east-1"
    eksClusterName: ""
  components:
    kagent:
      enabled: true
      path: "kagent"
      syncWave: "0"
    litellm:
      enabled: true
      path: "litellm"
      syncWave: "1"
    agentGateway:
      enabled: true
      path: "agent-gateway"
      syncWave: "2"
    langfuse:
      enabled: true
      path: "langfuse"
      syncWave: "1"
    jaeger:
      enabled: true
      path: "jaeger"
      syncWave: "0"
    tofuController:
      enabled: true
      path: "tofu-controller"
      syncWave: "-1"
    agentCore:
      enabled: false
      path: "agent-core-components"
      syncWave: "3"
  ```
- `gitops/addons/charts/agent-platform/templates/_helpers.tpl` — Standard Helm helpers
- `gitops/addons/charts/agent-platform/templates/namespace.yaml` — Agent platform namespace (conditional on `.Values.enabled`)
- `gitops/addons/charts/agent-platform/templates/kagent-application.yaml` — ArgoCD Application for Kagent (see DESIGN.md Section 4 for template). Conditional on `.Values.enabled` AND `.Values.components.kagent.enabled`
- `gitops/addons/charts/agent-platform/templates/litellm-application.yaml` — Same pattern for LiteLLM
- `gitops/addons/charts/agent-platform/templates/agent-gateway-application.yaml` — Same pattern for Agent Gateway
- `gitops/addons/charts/agent-platform/templates/langfuse-application.yaml` — Same pattern for Langfuse
- `gitops/addons/charts/agent-platform/templates/jaeger-application.yaml` — Same pattern for Jaeger
- `gitops/addons/charts/agent-platform/templates/tofu-controller-application.yaml` — Same pattern for Tofu Controller
- `gitops/addons/charts/agent-platform/templates/agent-core-application.yaml` — Same pattern for Agent Core
- `gitops/addons/charts/agent-platform/README.md` — Chart documentation

**Key Design Decisions (from DESIGN.md):**
- Each component gets its own ArgoCD Application (not a single monolithic app)
- Sync waves control deployment order: Tofu Controller (-1) → Kagent CRDs (-4) → Kagent/Jaeger (0) → LiteLLM/Langfuse (1) → Agent Gateway (2) → Agent Core (3)
- Each Application references a Helm chart in `sample-agent-platform-on-eks/gitops/<component>/`
- Values are passed from bridge chart to component charts via `spec.source.helm.values`

**Acceptance Criteria:**
- `helm template` with `enabled: false` produces zero resources
- `helm template` with `enabled: true` produces 7 ArgoCD Application resources (one per component)
- Each Application points to the correct path in `sample-agent-platform-on-eks`
- Sync waves are correctly set
- Resource prefix is parameterized (no hardcoded `peeks`)
- `kubectl apply --dry-run=client` validates all generated resources

---

#### Task 8.5 — Create Agent Platform Bootstrap Values

**Doc Reference:** DESIGN.md Section 6 (Configuration Management)

**Description:**
Create the default and environment-specific values files that configure the agent platform bridge chart.

**Files to Create:**
- `gitops/addons/default/addons/agent-platform/values.yaml` — Bootstrap defaults for agent platform components (see DESIGN.md Section 6, "Bootstrap Default"):
  ```yaml
  components:
    kagent:
      config:
        llmProvider: "bedrock"
        region: "us-east-1"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
    litellm:
      config:
        replicas: 2
        providers:
          - bedrock
  ```
- `gitops/addons/environments/control-plane/addons/agent-platform/values.yaml` — Control plane environment override (agent platform typically deploys to spokes, not hub)
- `gitops/addons/bootstrap/default/addons.yaml` — UPDATE: Add `agent-platform.enabled: false` entry

**Acceptance Criteria:**
- Default values provide sensible defaults for all components
- `addons.yaml` has the `agent-platform` entry (disabled by default)
- Environment overrides work correctly with the configuration hierarchy (DESIGN.md Section 6)

---

#### Task 8.6 — Add Agent Platform IAM Roles to `modules/hub-bootstrap`

**Doc Reference:** DESIGN.md Security Considerations section, COMPONENTS.md IAM Permissions

**Description:**
The agent platform components need IAM roles for IRSA/Pod Identity. These roles should be created by the `modules/hub-bootstrap` module (conditionally, when `enable_agent_platform = true`).

**Files to Change:**
- `modules/hub-bootstrap/iam.tf` — Add conditional IAM roles:
  - `KagentRole` — Bedrock InvokeModel permissions (see COMPONENTS.md)
  - `TofuControllerRole` — Bedrock agent management + IAM permissions (see COMPONENTS.md)
  - `LiteLLMRole` — Bedrock InvokeModel permissions
  - `AgentCoreRole` — Bedrock Agent Core permissions
  - All wrapped in `count = var.enable_agent_platform ? 1 : 0`
- `modules/hub-bootstrap/variables.tf` — Add `enable_agent_platform` variable (bool, default false)
- `modules/hub-bootstrap/outputs.tf` — Export role ARNs conditionally:
  ```hcl
  output "agent_platform_role_arns" {
    value = var.enable_agent_platform ? {
      kagent          = aws_iam_role.kagent[0].arn
      tofu_controller = aws_iam_role.tofu_controller[0].arn
      litellm         = aws_iam_role.litellm[0].arn
      agent_core      = aws_iam_role.agent_core[0].arn
    } : {}
  }
  ```
- `modules/hub-bootstrap/pod-identity.tf` — Add Pod Identity associations for agent platform service accounts (conditional)

**Acceptance Criteria:**
- When `enable_agent_platform = false`, no agent platform IAM roles are created
- When `enable_agent_platform = true`, all required IAM roles are created with least-privilege policies
- Role ARNs are exported for use by the bridge chart (passed as values to component charts)
- Pod Identity associations are created for agent platform service accounts

---

#### Task 8.7 — Create Agent Platform Hub-Config Example

**Doc Reference:** Section 5 (Consumption Patterns), DESIGN.md Section 6

**File to Create:** `examples/agent-platform/hub-config.yaml`

**Content:**
```yaml
domain_name: example.com
resource_prefix: myplatform

git:
  provider: github
  url: https://github.com/myorg/my-platform
  revision: main
  basepath: gitops/fleet/

identity:
  provider: cognito  # Or keycloak — agent platform works with any identity provider

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
      enable_backstage: true
      enable_keycloak: false       # Using Cognito
      enable_gitlab: false         # Using GitHub
      enable_kro: true
      enable_crossplane: true
      enable_agent_platform: true  # <-- Agent platform enabled
      # ... other addons as needed
```

**Also Create:** `examples/agent-platform/main.tf` — Terraform config that sources modules:
```hcl
module "hub_cluster" {
  source = "github.com/aws-samples/appmod-blueprints//modules/hub-cluster?ref=v1.0.0"
  # ...
}
module "hub_bootstrap" {
  source = "github.com/aws-samples/appmod-blueprints//modules/hub-bootstrap?ref=v1.0.0"
  enable_agent_platform = true
  # ...
}
```

**Also Create:** `examples/agent-platform/README.md` — Explains the agent platform deployment pattern

**Acceptance Criteria:**
- Config is valid and deployable
- Shows agent platform enabled with GitHub + Cognito (non-workshop path)
- Documents all agent-platform-specific addon flags
- `terraform validate` passes on the example

---

#### Task 8.8 — Add Agent Platform Secrets to `modules/hub-bootstrap`

**Doc Reference:** DESIGN.md Security Considerations (External Secrets), COMPONENTS.md

**Description:**
Agent platform components need secrets (API keys, database credentials, etc.) managed via AWS Secrets Manager and synced to Kubernetes via External Secrets Operator.

**Files to Change:**
- `modules/hub-bootstrap/secrets.tf` — Add conditional agent platform secrets:
  ```hcl
  # Agent platform secrets (conditional)
  resource "aws_secretsmanager_secret" "agent_platform" {
    count = var.enable_agent_platform ? 1 : 0
    name  = "${var.resource_prefix}/agent-platform"
  }
  resource "aws_secretsmanager_secret_version" "agent_platform" {
    count     = var.enable_agent_platform ? 1 : 0
    secret_id = aws_secretsmanager_secret.agent_platform[0].id
    secret_string = jsonencode({
      langfuse_postgres_password = random_password.langfuse_postgres[0].result
      litellm_master_key         = random_password.litellm_master_key[0].result
    })
  }
  ```
- Add `random_password` resources for Langfuse PostgreSQL and LiteLLM master key (conditional)

**Also Create (in bridge chart):**
- `gitops/addons/charts/agent-platform/templates/external-secret.yaml` — ExternalSecret that syncs agent platform secrets from AWS Secrets Manager to Kubernetes

**Acceptance Criteria:**
- Secrets are created in AWS Secrets Manager when `enable_agent_platform = true`
- ExternalSecret syncs secrets to `agent-platform` namespace
- No secrets created when agent platform is disabled
- Secrets follow the same pattern as existing platform secrets (see `secrets.tf`)

---

#### Task 8.9 — Validate Agent Platform on Modular Architecture (End-to-End)

**Doc Reference:** Section 8 (Success Criteria, item 6), DESIGN.md Section 8 (Testing Strategy)

**Description:**
End-to-end deployment test of the agent platform using the new modular approach. This validates that the agent platform works correctly on the upgraded, provider-agnostic architecture.

**Test Scenarios:**

**Scenario A: Agent Platform with GitHub + Cognito (non-workshop)**
1. Use `examples/agent-platform/hub-config.yaml` (GitHub, Cognito, no GitLab/Keycloak)
2. Deploy hub cluster via `modules/hub-cluster`
3. Deploy bootstrap via `modules/hub-bootstrap` with `enable_agent_platform = true`
4. Verify bridge chart creates 7 ArgoCD Applications
5. Verify all agent platform pods are running in `agent-platform` namespace
6. Create a test Kagent Agent CR and verify it works with Bedrock
7. Verify Langfuse and Jaeger are collecting traces
8. Disable agent platform (`enable_agent_platform = false`) and verify clean removal

**Scenario B: Agent Platform with GitLab + Keycloak (workshop path)**
1. Deploy from `platform-engineering-on-eks` repo with `enable_agent_platform = true`
2. Verify agent platform works alongside full workshop stack
3. Verify Agent Gateway auth works with Keycloak OIDC
4. Verify no regressions in core platform

**Scenario C: Feature flag toggle**
1. Start with `enable_agent_platform = false`
2. Enable → verify deployment
3. Disable → verify clean removal (all Applications pruned, pods terminated)
4. Re-enable → verify clean re-deployment

**Acceptance Criteria:**
- All 3 scenarios pass
- Agent platform deploys on modular architecture without forking
- Agent platform works with both GitHub+Cognito and GitLab+Keycloak
- Feature flag toggle is clean (no orphaned resources)
- Deployment time for agent platform components is ≤5 minutes after core platform is ready

---

#### Task 8.10 — Create Agent Platform Consumption Guide Section

**Doc Reference:** Section 5 (Consumption Patterns), Task 7.1

**Description:**
Add an "Agent Platform" section to `docs/CONSUMPTION-GUIDE.md` (created in Task 7.1) that explains how to enable and configure the agent platform.

**File to Update:** `docs/CONSUMPTION-GUIDE.md`

**Content to Add:**
- Pattern 5: Platform with Agent Platform — step-by-step guide
- How to enable agent platform via hub-config
- How to configure individual components (Kagent model, LiteLLM providers, etc.)
- How to deploy agent platform to specific spoke clusters only
- How to use environment overrides for dev vs prod agent platform config
- Link to `docs/agent-platform/DESIGN.md` for architecture details
- Link to `docs/agent-platform/README.md` for user guide

**Acceptance Criteria:**
- Agent platform consumption is documented alongside other patterns
- Step-by-step instructions are testable
- Links to detailed agent platform docs are correct
