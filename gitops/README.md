# GitOps Addon Management Platform

A complete GitOps-based addon management system for Kubernetes clusters using ArgoCD ApplicationSets, Helm charts, and Crossplane. Zero Terraform — the entire platform bootstraps from a Kind cluster.

## Quick Start

```bash
cd gitops

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
gitops/
├── Taskfile.yaml                Root Taskfile — delegates to cluster provider
├── config.yaml                  Shared platform config (repo, AWS, domain, IDC)
├── cluster-providers/           Cluster provisioning approaches (pluggable)
│   ├── kind-crossplane/         Kind + Crossplane bootstrap (zero Terraform)
│   │   ├── Taskfile.yml         Reads versions from registry, no duplicates
│   │   ├── kind.yaml            Kind cluster definition
│   │   ├── claims/              Hub cluster Crossplane claims
│   │   └── manifests/           ESO stores, ArgoCD projects
│   └── byoc/                    Bring Your Own Cluster
├── bootstrap/                   Hub self-management ApplicationSets
├── charts/
│   ├── appset-chart/            Unified Helm chart rendering ApplicationSets
│   └── fleet-secret/            Generates cluster secrets with enable_* labels
├── addons/
│   ├── registry/                Addon definitions split by domain
│   ├── configs/                 Per-addon Helm values and manifests
│   └── charts/                  Custom wrapper charts (rare)
├── overlays/
│   ├── environments/            Per-environment enablement and overrides
│   └── clusters/                Per-cluster overrides (use sparingly)
├── fleet/
│   ├── members/                 Fleet member cluster definitions
│   └── kro-values/              KRO cluster provisioning values
├── abstractions/                Shared Crossplane compositions (used by bootstrap AND hub)
│   └── resource-groups/
│       └── platform-cluster/    VPC + EKS + IAM + node groups composition
└── apps/                        Application workloads (future)
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

1. `charts/appset-chart/values.yaml` — chart defaults
2. `addons/registry/_defaults.yaml` — shared addon defaults
3. `addons/registry/core.yaml` etc. — addon definitions by domain
4. `overlays/environments/<env>/overrides.yaml` — environment-level appset overrides
5. `overlays/clusters/<cluster>/overrides.yaml` — cluster-level appset overrides

For addon Helm values (passed to the actual addon chart):

1. `addons/configs/<addon>/values.yaml` — default addon config
2. `overlays/environments/<env>/<addon>/values.yaml` — environment-specific
3. `overlays/clusters/<cluster>/<addon>/values.yaml` — cluster-specific

Missing files are silently skipped via `ignoreMissingValueFiles: true`.

## Key Directories

### `addons/registry/` — What to deploy

Domain-split addon definitions. Each addon entry has:
- `namespace` — target namespace (required, serves as iteration key)
- `selector` — which clusters get this addon (via `enable_<addon>` labels)
- `annotationsAppSet` — sync-wave ordering
- Chart source (chartRepository + defaultVersion) or git path

No `enabled` field — enablement is purely selector-driven.

Files: `_defaults.yaml`, `core.yaml`, `gitops.yaml`, `security.yaml`, `observability.yaml`, `platform.yaml`, `ml.yaml`

### `addons/configs/` — How to configure addons

Per-addon Helm values passed to the upstream chart:

```
addons/configs/argocd/values.yaml
addons/configs/external-secrets/values.yaml
addons/configs/ingress-nginx/values.yaml
```

### `overlays/environments/` — Per-environment configuration

- `enabled-addons.yaml` — which addons are on/off (feeds into cluster secret labels)
- `overrides.yaml` — appset-chart level overrides (version pins, selector changes)
- `<addon>/values.yaml` — environment-specific addon Helm values

### `overlays/clusters/` — Per-cluster overrides

For truly unique cluster config. Use sparingly.
- `addon-overrides.yaml` — override addon enablement for this cluster
- `<addon>/values.yaml` — cluster-specific addon Helm values

### `fleet/members/` — Cluster registration

One directory per cluster with ExternalSecret connection details and metadata.

### `bootstrap/` — Hub self-management

root-appset.yaml, addons.yaml, fleet-secrets.yaml, clusters.yaml

### `cluster-providers/` — Cluster provisioning (pluggable)

Multiple approaches for creating the hub cluster. Each provider must produce: ArgoCD running, a cluster secret with the right labels/annotations, and `bootstrap/root-appset.yaml` applied.

| Provider | Description |
|----------|-------------|
| `kind-crossplane/` | Kind + Crossplane — zero Terraform, full GitOps |
| `byoc/` | Bring Your Own Cluster — any existing cluster |

Key files in `kind-crossplane/`:

Taskfile.yaml, kind.yaml, claims/, manifests/

See [cluster-providers/README.md](cluster-providers/README.md) for the full provider contract, inputs/outputs, and handoff sequence.

## Common Operations

### Add a new addon

1. Add entry to `addons/registry/<domain>.yaml` (with namespace, selector, sync-wave)
2. Create `addons/configs/<addon>/values.yaml` with default Helm values
3. Add `enable_<addon>: true` to relevant `enabled-addons.yaml` files
4. Commit and push

### Enable an addon for an environment

Edit `overlays/environments/<env>/enabled-addons.yaml`:
```yaml
enabledAddons:
  grafana: true
```

### Override addon config per environment

Create `overlays/environments/<env>/<addon>/values.yaml` with Helm values.

### Override addon version per environment

Edit `overlays/environments/<env>/overrides.yaml`:
```yaml
cert-manager:
  defaultVersion: "v1.16.0"
```

### Add a new fleet member cluster

1. Create `fleet/members/<cluster>/values.yaml`
2. Ensure `enabled-addons.yaml` exists for the cluster's environment
3. Commit

### Per-cluster addon exception

Create `overlays/clusters/<cluster>/addon-overrides.yaml`:
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
| 1 | Ingress | ingress-nginx |
| 2 | Certificates | cert-manager |
| 3 | Security | keycloak, kyverno, otel |
| 4 | Platform | argo-workflows, kargo, backstage, grafana |
| 5 | ML/AI | jupyterhub, kubeflow, mlflow |
| 7 | Data | devlake |

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
  #   instanceTypes: ["m5.large"]    # Multiple types recommended for Spot
  #   desiredSize: 2
  #   minSize: 1
  #   maxSize: 5
  #   diskSize: 50                   # GB
  #   capacityType: "ON_DEMAND"      # ON_DEMAND or SPOT

# AWS configuration
aws:
  region: "us-west-2"
  accountId: "123456789012"
  profile: "default"                 # AWS CLI profile (local dev only)

# Domain and networking
domain: "idp.example.com"
resourcePrefix: "myplatform"         # Tags all AWS resources for identification
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

### Hub cluster defaults

By default, the hub runs EKS Auto Mode only — no managed node groups. Auto Mode handles compute, storage, networking, and load balancing with zero node management.

To add a managed node group (e.g., for workloads needing custom instance types or SSH access), add the `managedNodeGroup` block under `hub:` and set `enabled: true`. The node group runs in private subnets only, reuses the Auto Mode node IAM role, and supports both On-Demand and Spot capacity.

### Resource tagging

All composition resources (VPC, subnets, IGW, NAT, EIP, route tables, IAM roles, EKS cluster) are tagged with:
- `platform.gitops.io/cluster: <clusterName>`
- `platform.gitops.io/prefix: <resourcePrefix>`

## Hub Infrastructure Lifecycle

The hub cluster's AWS infrastructure (VPC, EKS, IAM roles, node groups) is created by Crossplane on the ephemeral Kind cluster during bootstrap. Once the hub is self-managing and Kind is deleted, these resources become unmanaged — they persist in AWS but nothing reconciles them.

This is intentional:
- The hub cluster is created once and rarely modified
- Having Crossplane manage the cluster it's running on creates circular dependency risks
- VPC, networking, and IAM roles are stable infrastructure that doesn't drift

Hub Crossplane (installed as an addon) manages fleet member clusters and application resources — not the hub itself.

If you need to modify hub infrastructure after bootstrap (e.g., change node group size, update Kubernetes version), use the AWS console or CLI directly.

Alternatively, re-run the Kind+Crossplane flow with updated config:

```bash
# 1. Edit config.yaml with new values (e.g., kubernetesVersion, vpcCidr, managedNodeGroup)
vim gitops/config.yaml

# 2. Run hub:update — spins up Kind, Crossplane adopts existing resources, applies changes, tears down
task hub:update
```

Crossplane matches existing AWS resources by `crossplane.io/external-name` and reconciles the diff rather than creating duplicates. The Kind cluster is ephemeral — created for the update, then deleted.

For fleet member clusters, Crossplane on the hub manages the full lifecycle — creation, updates, and deletion are all git-driven through the `bootstrap/clusters.yaml` ApplicationSet and KRO compositions.
