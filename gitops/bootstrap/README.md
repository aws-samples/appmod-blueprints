# Bootstrap

This directory makes the hub cluster self-managing. Once ArgoCD is running on the hub and `root-appset.yaml` is applied, the hub syncs this directory and takes over its own addon lifecycle -- no external controller needed.

## Files

| File | Sync-Wave | Purpose |
|------|-----------|---------|
| `root-appset.yaml` | -- | Entry point. Applied once by the cluster provider. Syncs the rest of this directory to the hub. |
| `addons.yaml` | -1 | Renders the appset-chart on the hub, producing one ApplicationSet per enabled addon. |
| `fleet-secrets.yaml` | 1 | Creates a fleet-secret Application per member cluster, generating cluster secrets with `enable_*` labels. |
| `clusters.yaml` | 5 | Deploys the `platform-cluster` Helm chart to provision fleet member clusters via Crossplane/KRO. |

## Bootstrap Sequence

1. The cluster provider (e.g. `kind-crossplane`) applies `root-appset.yaml` to the hub.
2. `root-appset.yaml` creates a `bootstrap` Application that syncs this directory (excluding itself) to the hub's ArgoCD.
3. ArgoCD applies the remaining three ApplicationSets in sync-wave order:
   - Wave -1: `addons.yaml` -- installs the addon pipeline on the hub.
   - Wave 1: `fleet-secrets.yaml` -- generates cluster secrets for each fleet member.
   - Wave 5: `clusters.yaml` -- provisions fleet member infrastructure.

## How root-appset.yaml Works

`root-appset.yaml` uses a `clusters` generator with `matchLabels: fleet_member: control-plane`. This means it only targets the hub cluster's own ArgoCD secret. It reads repo coordinates from the secret's annotations (`fleetRepoURL`, `fleetRepoRevision`, `fleetRepoBasepath`) and syncs the `bootstrap/` directory, excluding itself to avoid a loop.

## How addons.yaml Works

Uses a `clusters` generator matching `fleet_member: control-plane`. Renders the `appset-chart` Helm chart with the full addon registry (`_defaults.yaml`, `core.yaml`, `gitops.yaml`, etc.) plus environment and cluster overlays. The output is one ApplicationSet per addon definition, each with selectors that match `enable_*` labels on cluster secrets.

`preserveResourcesOnDeletion: false` -- removing an addon from the registry removes its ApplicationSet and all generated Applications.

## How fleet-secrets.yaml Works

Uses a matrix generator combining:
- `clusters` generator matching `fleet_member: control-plane` (the hub)
- `git` generator scanning `fleet/members/*/values.yaml`

For each fleet member, it renders the `fleet-secret` chart, which produces a Kubernetes Secret in the `argocd` namespace with labels like `enable_argocd: true`, `enable_external-secrets: true`, etc. These labels are what the addon ApplicationSets select on.

`preserveResourcesOnDeletion: true` -- removing a member from git does not delete its cluster secret (safety measure).

## How clusters.yaml Works

Uses a `clusters` generator matching `fleet_member: control-plane`. Deploys the `abstractions/resource-groups/platform-cluster` Helm chart with values from `fleet/kro-values/`. This creates `PlatformCluster` custom resources that Crossplane/KRO reconciles into VPC + EKS + IAM infrastructure.

Values are layered: default values, then per-tenant overrides.

## The control-plane Label

Every ApplicationSet in this directory uses the same generator selector:

```yaml
selector:
  matchLabels:
    fleet_member: control-plane
```

This label exists on the hub cluster's ArgoCD secret. It ensures these ApplicationSets only target the hub -- they read the hub's repo annotations and deploy to the hub's ArgoCD namespace. Fleet member clusters get their addons through the addon pipeline, not through these bootstrap ApplicationSets directly.
