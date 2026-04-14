# Fleet

Fleet member registration and cluster provisioning values.

## Directory Structure

```
fleet/
├── members/              Cluster registration (one dir per cluster)
│   └── <cluster>/
│       └── values.yaml   ExternalSecret config + metadata labels
└── kro-values/           KRO cluster provisioning config
    ├── default/
    │   └── kro-clusters/
    │       └── values.yaml   Default provisioning values for all clusters
    └── tenants/
        └── <tenant>/
            └── kro-clusters/
                └── values.yaml   Tenant-specific provisioning overrides
```

## How Fleet Members Are Discovered

The `bootstrap/fleet-secrets.yaml` ApplicationSet uses a matrix generator combining:

1. A `clusters` generator selecting the hub (`fleet_member: control-plane`)
2. A `git` file generator scanning `fleet/members/*/values.yaml`

For each discovered member, it renders the `charts/fleet-secret` Helm chart, which creates an ExternalSecret that produces an ArgoCD cluster secret with `enable_*` labels. The value files layered in are:

| Priority | Source | Purpose |
|----------|--------|---------|
| 1 | `fleet/members/<cluster>/values.yaml` | Cluster identity and ExternalSecret config |
| 2 | `overlays/environments/<env>/enabled-addons.yaml` | Addon enablement labels |
| 3 | `overlays/clusters/<cluster>/addon-overrides.yaml` | Per-cluster addon exceptions |

Missing files are silently skipped (`ignoreMissingValueFiles: true`).

## How to Register a New Fleet Member

1. Create a directory under `fleet/members/` named after the cluster:
   ```bash
   mkdir fleet/members/<cluster-name>
   ```

2. Create `fleet/members/<cluster-name>/values.yaml` with the required fields:
   ```yaml
   externalSecret:
     enabled: true
     secretStoreRefKind: ClusterSecretStore
     secretStoreRefName: aws-secrets-manager
     clusterName: <cluster-name>
     labels:
       environment: <environment-name>
       tenant: <tenant-name>
   ```

3. Ensure the cluster's environment has an `enabled-addons.yaml`:
   ```
   overlays/environments/<environment-name>/enabled-addons.yaml
   ```

4. Store the cluster's connection credentials in AWS Secrets Manager at key `<cluster-name>/config`.

5. Commit and push. The fleet-secrets ApplicationSet will detect the new file and create the cluster secret automatically.

### Required values.yaml Fields

| Field | Description |
|-------|-------------|
| `externalSecret.enabled` | Must be `true` |
| `externalSecret.secretStoreRefKind` | Secret store kind (typically `ClusterSecretStore`) |
| `externalSecret.secretStoreRefName` | Secret store name (typically `aws-secrets-manager`) |
| `externalSecret.clusterName` | Cluster name, must match the directory name and the Secrets Manager key |
| `externalSecret.labels.environment` | Environment name, used to resolve `enabled-addons.yaml` |
| `externalSecret.labels.tenant` | Tenant name, used to resolve KRO provisioning values |

## How KRO Values Feed Into Cluster Provisioning

The `bootstrap/clusters.yaml` ApplicationSet renders the `abstractions/resource-groups/platform-cluster` chart for each hub cluster, layering KRO values in this order:

1. `fleet/kro-values/default/kro-clusters/values.yaml` -- shared defaults
2. `fleet/kro-values/tenants/<tenant>/kro-clusters/values.yaml` -- tenant-specific overrides

Each values file defines a `clusters` map where each key becomes a PlatformCluster Crossplane claim:

```yaml
clusters:
  spoke-us-west-2:
    region: us-west-2
    clusterName: spoke-us-west-2
    vpcCidr: "10.1.0.0/16"
    kubernetesVersion: "1.32"
    autoMode: true
```

To provision a new fleet member cluster, add an entry to the appropriate tenant values file and commit.
