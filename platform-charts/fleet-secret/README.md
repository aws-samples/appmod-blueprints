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

## How to Register a New Fleet Member

1. Create `fleet/members/<cluster-name>/values.yaml` with the cluster's ExternalSecret config (clusterName, server, annotations).
2. Ensure an `enabled-addons.yaml` exists for the cluster's environment at `overlays/environments/<env>/enabled-addons.yaml`. Set desired addons to `true`.
3. Optionally create `overlays/clusters/<cluster-name>/addon-overrides.yaml` for per-cluster addon exceptions.
4. Commit and push. The `bootstrap/fleet-secrets.yaml` ApplicationSet picks up the new member directory and deploys the fleet-secret chart for it.
