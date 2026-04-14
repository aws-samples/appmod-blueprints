# Cluster Providers

This directory contains pluggable cluster provisioning approaches. The addon management
system (charts, addons, overlays, fleet, bootstrap) is independent of how the hub
cluster is created.

## Available Providers

| Provider | Description | When to use |
|----------|-------------|-------------|
| `kind-crossplane/` | Kind + Crossplane (zero Terraform) | Greenfield, full GitOps |
| `byoc/` | Bring Your Own Cluster | Existing cluster, any cloud provider |

## The Contract

Any provider must produce a running hub cluster that satisfies the conditions below. Once met, the addon management system takes over — the provider's job is done.

### Inputs

| Source | Fields | Purpose |
|--------|--------|---------|
| `config.yaml` | `hub.clusterName`, `aws.region`, `aws.accountId` | Cluster identity |
| `config.yaml` | `repo.url`, `repo.revision`, `repo.basepath` | Git source for ArgoCD |
| `config.yaml` | `domain`, `resourcePrefix`, `ingressName` | Ingress and naming |
| `config.yaml` | `identityCenter.*`, `argocdCapability.*` | EKS ArgoCD Capability setup |
| `addons/registry/core.yaml` | `argocd.defaultVersion`, `external-secrets.defaultVersion` | Versions (no hardcoding) |
| AWS credentials | IAM permissions | EKS, VPC, IAM, Secrets Manager, Pod Identity |
| `bootstrap/root-appset.yaml` | ApplicationSet manifest | Applied as the final step |

### Outputs

When bootstrap completes, the following must exist:

#### AWS Resources

| Resource | Details |
|----------|---------|
| EKS cluster | Running, accessible via ARN |
| VPC + subnets | Networking for the cluster |
| IAM roles | ArgoCD capability role, ESO pod identity role, Crossplane pod identity role |
| Pod identity associations | ESO and Crossplane mapped to their IAM roles |
| Secrets Manager `<cluster>/config` | Cluster metadata: repo URLs, region, account ID, domain, ingress config |

#### Hub Cluster Resources

| Resource | Namespace | Details |
|----------|-----------|---------|
| ArgoCD | (managed) | EKS ArgoCD Capability running — no pods in `argocd` namespace |
| External Secrets Operator | `external-secrets` | Installed via Helm before ArgoCD can manage it (chicken-and-egg) |
| ClusterSecretStore `aws-secrets-manager` | cluster-scoped | ESO can read from Secrets Manager |
| Seed cluster secret `<cluster>` | `argocd` | See below |
| `root-appset.yaml` | `argocd` | Bootstrap ApplicationSet applied |

#### Seed Cluster Secret

The seed secret is intentionally minimal — just enough for the bootstrap ApplicationSet to target the hub. The fleet-secret chart enriches it later.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <clusterName>
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    fleet_member: control-plane
    environment: control-plane
  annotations:
    addonsRepoURL: <repo.url>
    addonsRepoRevision: <repo.revision>
    addonsRepoBasepath: <repo.basepath>
    fleetRepoURL: <repo.url>
    fleetRepoRevision: <repo.revision>
    fleetRepoBasepath: <repo.basepath>
stringData:
  name: <clusterName>
  server: <clusterARN>
  config: '{"tlsClientConfig":{"insecure":false}}'
```

What the seed secret does NOT have (added later by fleet-secret chart via ExternalSecret):
- `enable_*` labels (from `enabled-addons.yaml`)
- `tenant` label (from `fleet/members/<cluster>/values.yaml`)
- `aws_cluster_name`, `aws_region`, `ingress_domain_name`, `resource_prefix` annotations (from Secrets Manager `<cluster>/config`)

### The Handoff

Once `root-appset.yaml` is applied, ArgoCD takes over:

```
root-appset.yaml applied
  -> ArgoCD syncs bootstrap/
       -> addons.yaml       — renders appset-chart -> one ApplicationSet per addon
       -> fleet-secrets.yaml — discovers fleet/members/ -> fleet-secret chart enriches seed secret
       -> clusters.yaml     — KRO cluster provisioning (no-op until fleet members defined)
```

The fleet-secret chart reads `fleet/members/<cluster>/values.yaml` and `enabled-addons.yaml`, pulls full config from `<cluster>/config` in Secrets Manager, and overwrites the seed secret with the complete set of labels and annotations. From this point, addon ApplicationSets match clusters via `enable_*` labels and the system is fully self-managing.

The bootstrap cluster (Kind) is now disposable — `task destroy-kind` removes it.

### Taskfile Interface

The root `gitops/Taskfile.yaml` delegates to providers by name. Each provider
must expose these tasks in its `Taskfile.yaml`:

| Task | Required | Description |
|------|----------|-------------|
| `install` | Yes | Full bootstrap: create cluster, install ArgoCD, apply root-appset |
| `status` | Yes | Show current state of cluster, apps, and managed resources |
| `destroy` | Yes | Full teardown: remove cluster and clean up all resources |
| `destroy-kind` | No | Remove ephemeral bootstrap cluster only (hub persists) |
| `hub:update` | No | Update hub infrastructure without full reinstall |
| `init` | No | Verify prerequisites (CLIs, credentials, config) |

The root Taskfile calls these as `<provider-name>:install`, etc.

### Configuration

Providers read shared configuration from `gitops/config.yaml`:

| Field | Description |
|-------|-------------|
| `clusterProvider` | Which provider to use (matches directory name) |
| `repo.url` | Git repository URL |
| `repo.revision` | Branch or tag |
| `repo.basepath` | Path prefix in the repo |
| `hub.clusterName` | Hub cluster name |
| `hub.kubernetesVersion` | Kubernetes version |
| `aws.region` | AWS region |
| `aws.accountId` | AWS account ID |
| `domain` | Base domain for ingress |
| `identityCenter.*` | AWS Identity Center config (for EKS ArgoCD Capability) |
| `argocdCapability.*` | ArgoCD capability config |

Provider-specific config (e.g., Kind node count, VPC CIDR) can live in the
provider's own directory but should not duplicate values from `config.yaml`.

## Adding a New Provider

1. Create a directory under `cluster-providers/` matching the provider name
2. Add a `Taskfile.yaml` exposing at minimum: `install`, `status`, `destroy`
3. Add a `README.md` explaining the approach
4. Register the include in `gitops/Taskfile.yaml`:
   ```yaml
   includes:
     my-provider:
       taskfile: ./cluster-providers/my-provider/Taskfile.yaml
       dir: ./cluster-providers/my-provider
       optional: true
   ```
5. Set `clusterProvider: "my-provider"` in `config.yaml` to use it
