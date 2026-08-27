# appset-chart

A single Helm chart that generates all ArgoCD ApplicationSets. It reads addon registry entries and renders one ApplicationSet per addon, each targeting clusters via label selectors on the ArgoCD cluster secret.

## How It Works

1. The chart's `values.yaml` provides base defaults (syncPolicy, repo URLs, valueFiles).
2. Registry files (`addons/registry/_defaults.yaml`, `core.yaml`, etc.) are merged in as additional value files, adding addon entries to `.Values`.
3. The main template (`application-set.yaml`) iterates over every `.Values` key that is a map with a `namespace` field -- each one becomes an ApplicationSet.
4. Each ApplicationSet uses a cluster generator with label selectors (`enable_<addon>: true`) to target the right clusters.
5. ArgoCD watches these ApplicationSets and creates an Application per matching cluster.

## Templates

| Template | Purpose |
|----------|---------|
| `application-set.yaml` | Main loop -- iterates all addon entries, renders one ApplicationSet per addon |
| `_application_set.tpl` | Helper templates: `valueFiles` (builds the 4-layer value file path list), `additionalResources` (renders extra sources for addons that need them) |
| `_git_matrix.tpl` | Matrix generator combining cluster generator with git file generator (for addons needing per-cluster git-sourced config) |
| `_pod_identity.tpl` | Generates an additional Helm source for ACK pod identity association |
| `_helpers.tpl` | Standard Helm helpers: name, fullname, chart label, common labels/annotations |

## Value File Layering

For each addon's Helm source, value files are resolved in this order (later wins):

1. `addons/configs/<addon>/values.yaml` -- default addon config
2. Per-addon custom `valueFiles` (if specified in the registry entry)
3. `overlays/environments/<env>/<addon>/values.yaml` -- environment-specific
4. `overlays/clusters/<cluster>/<addon>/values.yaml` -- cluster-specific

All paths use `ignoreMissingValueFiles: true`, so missing files are silently skipped.

## Cluster Secret Annotations

Addon registry entries use Go template expressions to pull values from the ArgoCD cluster secret's annotations. Common annotations:

| Annotation | Usage |
|------------|-------|
| `addonsRepoURL` | Git repository URL |
| `addonsRepoRevision` | Git branch/revision |
| `addonsRepoBasepath` | Base path within the repo |
| `aws_region` | AWS region |
| `aws_account_id` | AWS account ID |
| `aws_cluster_name` | EKS cluster name |
| `ingress_domain_name` | Ingress domain |
| `resource_prefix` | Resource naming prefix |

These are set on the cluster secret by the fleet-secret chart and referenced in registry entries via `{{.metadata.annotations.<key>}}`.

## Supported Addon Types

### Helm chart (upstream)

Registry entry has `chartRepository` and `defaultVersion`. The ApplicationSet source points to the external Helm repo. Value files from `addons/configs/` and overlays are layered in.

### Helm chart (git path)

Registry entry has `path:` pointing to a custom chart in `addons/charts/`. The source is the git repo at that path. Still gets Helm value file layering.

### Manifest

Registry entry has `type: manifest` and `path:`. The Helm block is skipped entirely -- ArgoCD applies the directory as raw Kubernetes manifests. Supports `directory.recurse` and `directory.exclude`.

### Additional resources

Registry entry has `additionalResources:` list. Each item adds an extra source to the ApplicationSet's multi-source Application. Supports manifest paths, external Helm charts, or arbitrary git paths.
