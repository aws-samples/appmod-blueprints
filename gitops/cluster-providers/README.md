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

### Infrastructure Output

Any provider must produce a Kubernetes cluster with:

1. **ArgoCD running** — either EKS ArgoCD Capability or self-managed in the `argocd` namespace
2. **A cluster secret** in the `argocd` namespace with:
   - Label: `argocd.argoproj.io/secret-type: cluster`
   - Label: `fleet_member: control-plane`
   - Label: `environment: control-plane`
   - Annotation: `addonsRepoURL` — git repo URL
   - Annotation: `addonsRepoRevision` — branch/tag
   - Annotation: `addonsRepoBasepath` — path prefix in the repo
   - Annotation: `fleetRepoURL` — fleet repo URL (can be same as addons)
   - Annotation: `fleetRepoRevision` — branch/tag
   - Annotation: `fleetRepoBasepath` — path prefix
3. **`bootstrap/root-appset.yaml` applied** — this kicks off the addon pipeline

Once these three conditions are met, the addon management system takes over.

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
