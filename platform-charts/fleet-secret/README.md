# fleet-secret

Generates ArgoCD cluster secrets via ExternalSecret, with `enable_*` labels derived from `enabled-addons.yaml`. This is the bridge between "which addons are enabled" (git) and "which clusters get which addons" (ArgoCD label selectors).

## How It Works

1. Each fleet member has a Helm release of this chart, parameterized with the cluster's `enabled-addons.yaml` as a value file.
2. The chart creates an ExternalSecret in the `argocd` namespace that pulls cluster connection details (server URL, auth config) from AWS Secrets Manager.
3. The ExternalSecret's `target.template` section generates labels and annotations on the resulting Kubernetes Secret.
4. For each entry in `enabledAddons` that is `true`, a label `enable_<addon>: 'true'` is added to the secret.
5. The appset-chart's ApplicationSets use cluster generator selectors that match these `enable_*` labels, so addons are deployed only to clusters that have them enabled.

## Label and Annotation Structure

The generated cluster secret gets:

Labels:
- `argocd.argoproj.io/secret-type: cluster` -- marks it as an ArgoCD cluster secret
- `enable_<addon>: 'true'` -- one per enabled addon (from `enabledAddons` map)
- Additional labels from the Secrets Manager entry's `addons` field
- Any extra labels from `.Values.externalSecret.labels`

Annotations:
- Cluster metadata from the Secrets Manager entry's `metadata` field (aws_region, aws_cluster_name, ingress_domain_name, etc.)
- Any extra annotations from `.Values.externalSecret.annotations`

## values.yaml

```yaml
externalSecret:
  enabled: true
  secretStoreRefKind: ClusterSecretStore
  secretStoreRefName: aws-secrets-manager
  clusterName: ""          # Name of the cluster (used as secret name and SM key prefix)
  server: ""               # Cluster API server URL (optional, can come from SM)
  annotations: {}          # Extra annotations on the cluster secret
  labels: {}               # Extra labels on the cluster secret

overlay:                   # External overlay repo ("layer 5") -- OPTIONAL, default off
  repoURL: ""              # Consumer repo that may override platform addon values
  revision: "main"         # MUST contain the overlay files
  basepath: ""             # Root holding configs/ + overlays/ (e.g. "gitops/")

enabledAddons: {}          # Populated from enabled-addons.yaml via valueFiles
```

## How Addon ApplicationSets Use These Labels

Each addon's registry entry defines a selector:

```yaml
selector:
  matchExpressions:
    - key: enable_grafana
      operator: In
      values: ['true']
```

The appset-chart renders this into the ApplicationSet's cluster generator. ArgoCD matches it against the `enable_grafana: 'true'` label on the cluster secret. If the label exists and is `true`, an Application is created for that addon on that cluster.

## External Overlay Repo ("layer 5")

### The problem it solves

The appset-chart layers Helm value files per addon, low to high precedence:

1. `$defaults/<basepath>addons/configs/<addon>/values.yaml`
2. per-addon `valueFiles` from the registry entry
3. `$defaults/<basepath>overlays/environments/<env>/<addon>/values.yaml`
4. `$defaults/<basepath>overlays/clusters/<cluster>/<addon>/values.yaml`

`$defaults` resolves to the repo that **owns the addon** -- the one holding its chart and registry entry. So for an addon defined in this repo, layers 3 and 4 are read from this repo. A consumer repo that wants to change one value for one cluster would otherwise have to open a PR here.

Worse, it fails *silently*: all these paths carry `ignoreMissingValueFiles: true`, so a `values.yaml` placed in the wrong repo is skipped without error, and the setting just never takes effect.

Layer 5 fixes this. Point `overlay.repoURL` at the consumer repo and the appset-chart appends a `$overlay` source plus three more value files per addon, **after** layers 1-4:

```
$overlay/<basepath>configs/<addon>/values.yaml
$overlay/<basepath>overlays/environments/<env>/<addon>/values.yaml
$overlay/<basepath>overlays/clusters/<cluster>/<addon>/values.yaml
```

Being last, the consumer's file wins.

### How to use it

**1. Set `overlay` in the fleet-member values** (`fleet/<hub|members/<cluster>>/values.yaml`):

```yaml
overlay:
  repoURL: https://github.com/my-org/my-consumer-repo.git
  revision: main
  basepath: gitops/
```

This renders `overlay_repo_url` / `overlay_repo_revision` / `overlay_repo_basepath` onto that cluster's secret. It is **per-cluster** -- clusters without it keep reading overlays from the addon's own repo.

**2. Add the override in the consumer repo**, at the path for the addon and cluster:

```
<basepath>overlays/clusters/<cluster>/<addon>/values.yaml
```

For example, to enable a chart flag for the `karpenter` addon on the `hub` cluster, with `basepath: gitops/`:

```yaml
# gitops/overlays/clusters/hub/karpenter/values.yaml   (in the CONSUMER repo)
node:
  manageAddons: true
```

The file takes the **addon chart's** value schema -- the same shape as `addons/charts/<addon>/values.yaml`.

**3. Verify it resolved.** The generated Application should now have three sources and `$overlay` value files:

```sh
kubectl get application <addon>-<cluster> -n argocd -o yaml | grep -A5 valueFiles
```

If `$overlay` entries are absent, the annotation did not reach the cluster secret:

```sh
kubectl get secret <cluster> -n argocd -o jsonpath='{.metadata.annotations.overlay_repo_url}'
```

### Caveats

- **`$overlay` is a real ArgoCD source.** If the URL is unreachable or needs credentials ArgoCD does not have, **every** overlay-aware app on that cluster breaks -- not just the one you are overriding. Register a repo credential first, and prefer wiring this late in a bootstrap sequence, after the repo exists.
- **`revision` must contain the files.** Pointing at a branch without them means the overlay silently no-ops (`ignoreMissingValueFiles`), and the value quietly stays at its in-repo default. Remember to update `revision` when the work merges to the default branch.
- **It also repoints the appset-level `overrides.yaml`.** Independently of the per-addon layers, `bootstrap/addons.yaml` reads `$overlay/<basepath>overlays/{environments/<env>,clusters/<cluster>}/overrides.yaml`, which fall back to this repo when the annotation is unset. Setting it moves those reads to the consumer repo too. Those files take the **registry entry** schema (addon-keyed, with `valuesObject` / `defaultVersion`), not chart values -- so they can override registry-level settings, but chart values placed there do nothing.
- **Only the platform appset consumes these annotations.** A consumer repo running its own appset (with its own registry files) does not set `overlayRepoURLGit`, so its addons keep resolving overlays through layer 4 as before. No double-read.

## How to Register a New Fleet Member

1. Create `fleet/members/<cluster-name>/values.yaml` with the cluster's ExternalSecret config (clusterName, server, annotations).
2. Ensure an `enabled-addons.yaml` exists for the cluster's environment at `overlays/environments/<env>/enabled-addons.yaml`. Set desired addons to `true`.
3. Optionally create `overlays/clusters/<cluster-name>/addon-overrides.yaml` for per-cluster addon exceptions.
4. Commit and push. The `bootstrap/fleet-secrets.yaml` ApplicationSet picks up the new member directory and deploys the fleet-secret chart for it.
