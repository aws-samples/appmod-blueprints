# Overlays

Environment and cluster-specific configuration overrides.

## Directory Structure

```
overlays/
├── environments/
│   └── <env>/
│       ├── enabled-addons.yaml        Addon enablement map (boolean flags)
│       ├── overrides.yaml             AppSet-level value overrides
│       └── <addon>/
│           └── values.yaml            Environment-specific addon Helm values
└── clusters/
    └── <cluster>/
        ├── addon-overrides.yaml       Per-cluster addon enablement exceptions
        └── <addon>/
            └── values.yaml            Cluster-specific addon Helm values
```

## Value Layering

Values are merged in order (later wins). Missing files are silently skipped via `ignoreMissingValueFiles: true`.

For addon enablement labels on the cluster secret:

| Priority | Source |
|----------|--------|
| 1 | `fleet/members/<cluster>/values.yaml` |
| 2 | `overlays/environments/<env>/enabled-addons.yaml` |
| 3 | `overlays/clusters/<cluster>/addon-overrides.yaml` |

For addon Helm values passed to the actual chart:

| Priority | Source |
|----------|--------|
| 1 | `addons/configs/<addon>/values.yaml` -- defaults |
| 2 | `overlays/environments/<env>/<addon>/values.yaml` -- environment |
| 3 | `overlays/clusters/<cluster>/<addon>/values.yaml` -- cluster |

For appset-chart overrides (version pins, selector changes):

| Priority | Source |
|----------|--------|
| 1 | `addons/registry/_defaults.yaml` + domain files |
| 2 | `overlays/environments/<env>/overrides.yaml` |
| 3 | `overlays/clusters/<cluster>/overrides.yaml` |

## enabled-addons.yaml Format

A flat map of addon keys (underscores, matching `enable_<addon>` label convention) to booleans. Every known addon should be listed explicitly:

```yaml
enabledAddons:
  argocd: false
  metrics_server: true
  external_secrets: true
  keycloak: true
  crossplane: true
  # ...
```

The `fleet-secret` chart iterates this map and generates `enable_<addon>: 'true'` labels on the ArgoCD cluster secret. The `appset-chart` selectors then match these labels to deploy addons.

## How to Create a New Environment

1. Create the environment directory:
   ```bash
   mkdir overlays/environments/<env-name>
   ```

2. Create `enabled-addons.yaml` listing all addons with their desired state:
   ```yaml
   enabledAddons:
     argocd: false
     metrics_server: true
     # ... list all addons
   ```

3. Optionally create `overrides.yaml` for appset-level overrides (version pins, etc.):
   ```yaml
   cert_manager:
     defaultVersion: "v1.16.0"
   ```

4. Optionally create `<addon>/values.yaml` subdirectories for environment-specific Helm values.

5. Register fleet members that reference this environment via `externalSecret.labels.environment` in their `fleet/members/<cluster>/values.yaml`.

## How to Add Per-Cluster Addon Overrides

Use sparingly -- prefer environment-level configuration.

1. Create the cluster directory:
   ```bash
   mkdir -p overlays/clusters/<cluster-name>
   ```

2. To override addon enablement, create `addon-overrides.yaml`:
   ```yaml
   enabledAddons:
     jupyterhub: true
   ```

3. To override addon Helm values, create `<addon>/values.yaml`:
   ```bash
   mkdir overlays/clusters/<cluster-name>/<addon>
   # Add values.yaml with cluster-specific Helm values
   ```
