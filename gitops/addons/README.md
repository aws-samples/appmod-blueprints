# Addons

Addon catalog, configuration, and custom charts for the GitOps platform. Everything ArgoCD needs to know about an addon lives here.

## Directory Structure

```
addons/
├── registry/       What can be deployed — addon definitions split by domain
├── configs/        How to configure them — default Helm values per addon
└── charts/         Custom wrapper charts — when upstream charts aren't enough
```

## How the Three Directories Relate

1. `registry/` defines each addon: its chart source, namespace, sync-wave, and cluster selector.
2. `configs/` provides the default Helm values passed to the addon's chart at deploy time.
3. `charts/` holds custom Helm charts for addons that wrap multiple upstream charts or need extra resources (e.g., ExternalSecrets, IAM roles). Registry entries for these addons use a `path:` field pointing here instead of `chartRepository`.

The appset-chart reads registry entries to generate ArgoCD ApplicationSets. Each ApplicationSet references the corresponding `configs/<addon>/values.yaml` as a value file source. Missing files are silently skipped.

## configs/

One directory per addon containing default Helm values and optional manifests:

```
configs/
├── argocd/values.yaml
├── external-secrets/
│   ├── values.yaml
│   └── manifests/          Additional raw manifests (used via additionalResources)
├── ingress-nginx/values.yaml
└── ...
```

These are the base values. Environment and cluster overlays in `overlays/` layer on top.

## charts/

Custom wrapper Helm charts for addons that need more than a single upstream chart:

```
charts/
├── keycloak/               Wraps Keycloak + ExternalSecrets + PushSecret
├── grafana/                Wraps Grafana + IAM + ingress config
├── backstage/              Wraps Backstage + ExternalSecrets
└── ...
```

Each has a standard Helm structure (`Chart.yaml`, `values.yaml`, `templates/`). Registry entries reference these via `path:` instead of `chartRepository`.

## How to Add a New Addon

1. Add an entry to `registry/<domain>.yaml` with the required fields (`namespace`, `selector`, `annotationsAppSet`, and either `chartRepository`/`defaultVersion` or `path`). See `registry/README.md` for field details.

2. Create `configs/<addon-name>/values.yaml` with default Helm values for the upstream chart. Skip this if the addon needs no custom values.

3. If the addon requires a custom wrapper chart (multiple sub-charts, ExternalSecrets, IAM resources), create `charts/<addon-name>/` with a standard Helm chart. Point the registry entry's `path:` to it.

4. Add `enable_<addon_name>: true` to the relevant `overlays/environments/<env>/enabled-addons.yaml` files.

5. Commit and push. ArgoCD picks up the change automatically.
