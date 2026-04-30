# GitOps Addon Management Platform

A complete GitOps-based addon management system for Kubernetes clusters using ArgoCD ApplicationSets, Helm charts, and Crossplane. Zero Terraform — the entire platform bootstraps from a Kind cluster.

## Quick Start

```bash
# 1. Edit config with your environment values
vim config.yaml

# 2. Bootstrap the platform (reads clusterProvider from config.yaml)
task install

# 3. Monitor progress
task status

# 4. Once hub is self-managing, remove Kind
task destroy-kind
```

## Directory Structure

```
├── Taskfile.yaml                Root Taskfile — delegates to cluster provider
├── config.yaml                  Shared platform config (repo, AWS, domain, IDC)
├── cluster-providers/           Cluster provisioning approaches (pluggable)
│   ├── kind-crossplane/         Kind + Crossplane bootstrap (zero Terraform)
│   │   ├── Taskfile.yml         Reads versions from registry, no duplicates
│   │   ├── kind.yaml            Kind cluster definition
│   │   ├── claims/              Hub cluster Crossplane claims
│   │   └── manifests/           ESO stores, ArgoCD projects
│   └── byoc/                    Bring Your Own Cluster
├── platform-charts/             Platform infrastructure Helm charts
│   ├── appset-chart/            Unified Helm chart rendering ApplicationSets
│   └── fleet-secret/            Generates cluster secrets with enable_* labels
├── gitops/
│   ├── bootstrap/               Hub self-management ApplicationSets
│   ├── addons/
│   │   ├── registry/            Addon definitions split by domain
│   │   ├── configs/             Per-addon Helm values and manifests
│   │   └── charts/              Custom wrapper charts (rare)
│   ├── overlays/
│   │   ├── environments/        Per-environment enablement and overrides
│   │   └── clusters/            Per-cluster overrides (use sparingly)
│   ├── fleet/
│   │   ├── members/             Fleet member cluster definitions
│   │   └── kro-values/          KRO cluster provisioning values
│   ├── abstractions/            Shared Crossplane compositions (used by bootstrap AND hub)
│   │   └── resource-groups/
│   │       └── platform-cluster/  VPC + EKS + IAM + node groups composition
│   └── apps/                    Application workloads (future)
└── gitops-old/                  Previous gitops structure (deprecated)
```

## How It Works

### Bootstrap Sequence

```
task install
  -> Kind cluster created
       -> ArgoCD installed (helm)
            -> appset-chart installed with bootstrap-addons.yaml
                 -> Crossplane provisions AWS infra (VPC, EKS, IAM)
                      -> External Secrets creates hub cluster secret
                           -> ArgoCD deploys to hub (ArgoCD + bootstrap/)
                                -> Hub ArgoCD becomes self-managing
                                     -> Kind cluster deleted
```

### Addon Enablement Flow

```
enabled-addons.yaml (git)
  -> fleet-secret chart reads it
       -> Generates enable_* labels on cluster secret
            -> appset-chart selectors match labels
                 -> ApplicationSet creates Application for addon
                      -> ArgoCD deploys addon to cluster
```

### Value Layering

Values are merged in this order (later wins):

For the appset-chart (controls which ApplicationSets get rendered):

1. `platform-charts/appset-chart/values.yaml` — chart defaults
2. `gitops/addons/registry/_defaults.yaml` — shared addon defaults
3. `gitops/addons/registry/core.yaml` etc. — addon definitions by domain
4. `gitops/overlays/environments/<env>/overrides.yaml` — environment-level appset overrides
5. `gitops/overlays/clusters/<cluster>/overrides.yaml` — cluster-level appset overrides

For addon Helm values (passed to the actual addon chart):

1. `gitops/addons/configs/<addon>/values.yaml` — default addon config
2. `gitops/overlays/environments/<env>/<addon>/values.yaml` — environment-specific
3. `gitops/overlays/clusters/<cluster>/<addon>/values.yaml` — cluster-specific

Missing files are silently skipped via `ignoreMissingValueFiles: true`.

## Key Directories

### `gitops/addons/registry/` — What to deploy

Domain-split addon definitions. Each addon entry has:
- `namespace` — target namespace (required, serves as iteration key)
- `selector` — which clusters get this addon (via `enable_<addon>` labels)
- `annotationsAppSet` — sync-wave ordering
- Chart source (chartRepository + defaultVersion) or git path

No `enabled` field — enablement is purely selector-driven.

Files: `_defaults.yaml`, `core.yaml`, `gitops.yaml`, `security.yaml`, `observability.yaml`, `platform.yaml`, `ml.yaml`

### `gitops/addons/configs/` — How to configure addons

Per-addon Helm values passed to the upstream chart:

```
gitops/addons/configs/argocd/values.yaml
gitops/addons/configs/external-secrets/values.yaml
gitops/addons/configs/ingress-nginx/values.yaml
```

### `gitops/overlays/environments/` — Per-environment configuration

- `enabled-addons.yaml` — which addons are on/off (feeds into cluster secret labels)
- `overrides.yaml` — appset-chart level overrides (version pins, selector changes)
- `<addon>/values.yaml` — environment-specific addon Helm values

### `gitops/overlays/clusters/` — Per-cluster overrides

For truly unique cluster config. Use sparingly.
- `addon-overrides.yaml` — override addon enablement for this cluster
- `<addon>/values.yaml` — cluster-specific addon Helm values

### `gitops/fleet/members/` — Cluster registration

One directory per cluster with ExternalSecret connection details and metadata.

### `gitops/bootstrap/` — Hub self-management

root-appset.yaml, addons.yaml, fleet-secrets.yaml, clusters.yaml

### `cluster-providers/` — Cluster provisioning (pluggable)

Multiple approaches for creating the hub cluster. Each provider must produce: ArgoCD running, a cluster secret with the right labels/annotations, and `bootstrap/root-appset.yaml` applied.

| Provider | Description |
|----------|-------------|
| `kind-crossplane/` | Kind + Crossplane — zero Terraform, full GitOps |
| `byoc/` | Bring Your Own Cluster — any existing cluster |

Key files in `kind-crossplane/`:

Taskfile.yaml, kind.yaml, claims/, manifests/

See [cluster-providers/kind-crossplane/README.md](cluster-providers/kind-crossplane/README.md) for the full provider contract, inputs/outputs, and handoff sequence.

## Common Operations

### Add a new addon

1. Add entry to `gitops/addons/registry/<domain>.yaml` (with namespace, selector, sync-wave)
2. Create `gitops/addons/configs/<addon>/values.yaml` with default Helm values
3. Add `enable_<addon>: true` to relevant `enabled-addons.yaml` files
4. Commit and push

### Enable an addon for an environment

Edit `gitops/overlays/environments/<env>/enabled-addons.yaml`:
```yaml
enabledAddons:
  grafana: true
```

### Override addon config per environment

Create `gitops/overlays/environments/<env>/<addon>/values.yaml` with Helm values.

### Override addon version per environment

Edit `gitops/overlays/environments/<env>/overrides.yaml`:
```yaml
cert-manager:
  defaultVersion: "v1.16.0"
```

### Add a new fleet member cluster

Adding a spoke cluster is a three-part process: provision the infrastructure, register it as a fleet member, and ensure its environment has addon enablement configured.

**Step 1: Provision the cluster via KRO values**

Add an entry to the appropriate tenant values file. For example, `gitops/fleet/kro-values/tenants/control-plane/kro-clusters/values.yaml`:

```yaml
clusters:
  spoke-us-west-2:
    region: us-west-2
    clusterName: spoke-us-west-2
    vpcCidr: "10.1.0.0/16"
    kubernetesVersion: "1.35"
    autoMode: true
    resourcePrefix: peeks
```

The `bootstrap/clusters.yaml` ApplicationSet picks this up and renders a `PlatformCluster` Crossplane claim. Crossplane provisions the VPC, subnets, EKS cluster, IAM roles, and all networking.

**Step 2: Register as a fleet member**

Create `gitops/fleet/members/spoke-us-west-2/values.yaml`:

```yaml
externalSecret:
  enabled: true
secretStoreRefKind: ClusterSecretStore
secretStoreRefName: aws-secrets-manager
clusterName: spoke-us-west-2
labels:
  environment: production
  tenant: control-plane
```

The `bootstrap/fleet-secrets.yaml` matrix generator detects the new file and creates an ExternalSecret that produces an ArgoCD cluster secret with `enable_*` labels.

**Step 3: Create the environment's enabled-addons (if new)**

If the environment doesn't exist yet, create `gitops/overlays/environments/production/enabled-addons.yaml`:

```yaml
enabledAddons:
  metrics_server: true
  external_secrets: true
  ingress_class_alb: true
  aws_load_balancer_controller: true
```

If the environment already exists, this step is not needed.

**Step 4: Seed cluster credentials and commit**

The spoke's connection credentials must be seeded in AWS Secrets Manager before the ExternalSecret can pull them. This step is provider-specific — see your cluster provider's README:
- [kind-crossplane](cluster-providers/kind-crossplane/README.md#spoke-cluster-provisioning)
- [byoc](cluster-providers/byoc/README.md)

Then commit and push:

```bash
git add gitops/fleet/ gitops/overlays/
git commit -m "Add spoke-us-west-2 fleet member"
git push
```

ArgoCD picks up the changes automatically:
- `clusters.yaml` → Crossplane provisions the EKS cluster
- `fleet-secrets.yaml` → creates the cluster secret with `enable_*` labels
- `addons.yaml` → deploys enabled addons to the spoke

See [gitops/fleet/README.md](gitops/fleet/README.md) for detailed field reference and value layering.

### Per-cluster addon exception

Create `gitops/overlays/clusters/<cluster>/addon-overrides.yaml`:
```yaml
enabledAddons:
  jupyterhub: true
```

## Sync-Wave Reference

| Wave | Category | Addons |
|------|----------|--------|
| -5 | Multi-account | multi-acct |
| -3 | Abstractions | kro |
| -2 | KRO Resource Groups | kro-manifests, kro-manifests-hub |
| -1 | Controllers | external-secrets, ACK controllers |
| 0 | Core | argocd, metrics-server |
| 1 | Ingress | ingress-class-alb |
| 2 | Certificates | cert-manager |
| 3 | Security/Observability | kyverno, argo-rollouts, argo-events, crossplane-base, grafana-operator, kube-state-metrics, otel |
| 4 | Platform | efs-csi, grafana, kyverno-policies, kyverno-policy-reporter, kargo, flux, crossplane-aws |
| 5 | Networking/ML/AI | lbc, external-dns, jupyterhub, kubeflow, mlflow, ray-operator, spark-operator, airflow, grafana-dashboards, cw-prometheus |
| 6 | Security | keycloak |
| 7 | GitOps | argo-workflows |

## Running Multiple Stacks

Multiple platform instances can coexist in the same AWS account. Each stack must have unique values for:

| Setting | Why | Example |
|---------|-----|---------|
| `hub.clusterName` | EKS cluster names are region-scoped. IAM roles, policies, and Secrets Manager keys are prefixed with clusterName. | `hub`, `hub-staging` |
| `domain` | Ingress hostnames, Route53 records, TLS certificates, and OIDC issuer URLs are derived from domain. | `dev.idp.example.com`, `staging.idp.example.com` |
| `hub.vpcCidr` | VPC CIDRs must not overlap if VPC peering is needed. | `10.0.0.0/16`, `10.1.0.0/16` |

Resources automatically isolated by clusterName (no manual action):
- IAM roles: `{clusterName}-CrossplaneIAMProviderRole`, `{clusterName}-ESOPodIdentityRole`, etc.
- IAM policies: `{clusterName}-ESOSecretsManagerPolicy`, `{clusterName}-LBCControllerPolicy`, etc.
- Secrets Manager: `{clusterName}/config`, `{clusterName}/keycloak`
- EKS Pod Identity Associations: scoped to EKS cluster
- Kind bootstrap cluster: named `{clusterName}-bootstrap`

Resources that require unique config.yaml values:
- EKS cluster name (from `hub.clusterName`)
- DNS records and ingress hostnames (from `domain`)
- TLS certificates (from `domain`)
- OIDC issuer URL (from `domain`)

Example for two stacks in the same account:

```yaml
# Stack 1: config.yaml
hub:
  clusterName: "hub-dev"
domain: "dev.idp.example.com"

# Stack 2: config.yaml
hub:
  clusterName: "hub-staging"
domain: "staging.idp.example.com"
```

## Prerequisites

- kind
- kubectl
- helm 3.x
- yq
- aws CLI (configured with credentials)

## Configuration Reference (`config.yaml`)

All platform settings are centralized in `config.yaml`. Edit before running `task install`.

```yaml
# Cluster provider — which approach to use for hub cluster provisioning
clusterProvider: "kind-crossplane"   # Options: kind-crossplane, byoc

# Git repository hosting the gitops platform code
repo:
  url: "https://github.com/your-org/your-repo.git"
  revision: "main"
  basepath: "gitops/"

# Hub cluster configuration
hub:
  clusterName: "hub"                 # EKS cluster name
  kubernetesVersion: "1.32"          # EKS Kubernetes version
  vpcCidr: "10.0.0.0/16"            # VPC CIDR block

  # Optional: managed node group alongside Auto Mode
  # managedNodeGroup:
  #   enabled: true
  #   instanceTypes: ["m5.large"]
  #   desiredSize: 2
  #   minSize: 1
  #   maxSize: 5
  #   diskSize: 50
  #   capacityType: "ON_DEMAND"

# AWS configuration
aws:
  region: "us-west-2"
  accountId: "123456789012"
  profile: "default"

# Domain and networking
domain: "idp.example.com"
resourcePrefix: "myplatform"
ingressName: "hub-ingress"
ingressSecurityGroups: ""

# AWS Identity Center (required for EKS ArgoCD Capability)
identityCenter:
  instanceArn: "arn:aws:sso:::instance/ssoins-xxx"
  region: "us-east-1"
  adminGroupId: "group-id-here"

# EKS ArgoCD Capability
argocdCapability:
  name: "argocd"
```

## Hub Infrastructure Lifecycle

The hub cluster's AWS infrastructure (VPC, EKS, IAM roles, node groups) is created by Crossplane on the ephemeral Kind cluster during bootstrap. Once the hub is self-managing and Kind is deleted, these resources become unmanaged — they persist in AWS but nothing reconciles them.

This is intentional:
- The hub cluster is created once and rarely modified
- Having Crossplane manage the cluster it's running on creates circular dependency risks
- VPC, networking, and IAM roles are stable infrastructure that doesn't drift

Hub Crossplane (installed as an addon) manages fleet member clusters and application resources — not the hub itself.

To modify hub infrastructure after bootstrap:

```bash
# 1. Edit config.yaml with new values
vim config.yaml

# 2. Run hub:update — spins up Kind, Crossplane adopts existing resources, applies changes, tears down
task hub:update
```

Crossplane matches existing AWS resources by `crossplane.io/external-name` and reconciles the diff rather than creating duplicates. The Kind cluster is ephemeral — created for the update, then deleted.

For fleet member clusters, Crossplane on the hub manages the full lifecycle — creation, updates, and deletion are all git-driven through the `bootstrap/clusters.yaml` ApplicationSet and KRO compositions.
