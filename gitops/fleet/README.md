# Fleet Management

This folder defines the spoke cluster fleet — which clusters exist, how they're provisioned, and what addons they receive.

## Directory Structure

```
fleet/
├── hub/                          # Hub cluster configuration
│   └── values.yaml
├── members/                      # Fleet membership (ArgoCD cluster secrets)
│   └── <cluster-name>/
│       └── values.yaml           # Registers cluster as ArgoCD target
└── spoke-values/                 # Spoke cluster provisioning
    ├── default/
    │   └── crossplane-clusters/
    │       └── values.yaml       # Shared defaults for Crossplane clusters
    └── tenants/<tenant>/
        ├── crossplane-clusters/
        │   └── values.yaml       # Clusters provisioned via Crossplane
        └── kro-clusters/
            └── values.yaml       # Clusters provisioned via KRO
```

## How to Add a Spoke Cluster

### Step 1: Choose your provisioning method

| Method | Path | Provisioner | Use when |
|--------|------|-------------|----------|
| Crossplane | `spoke-values/tenants/<tenant>/crossplane-clusters/values.yaml` | Crossplane XRD `PlatformCluster` | Full VPC + EKS + IAM via Crossplane composition |
| KRO | `spoke-values/tenants/<tenant>/kro-clusters/values.yaml` | KRO `EksclusterWithVpc` ResourceGroup | Cluster provisioning via KRO + ACK |

### Step 2: Define the cluster

Add an entry under `clusters:` in the appropriate values file.

**Crossplane example** (`spoke-values/tenants/workshop/crossplane-clusters/values.yaml`):

```yaml
clusters:
  my-spoke:
    clusterName: my-spoke
    vpcCidr: "10.3.0.0/16"
    kubernetesVersion: "1.35"
    autoMode: true
    resourcePrefix: peeks
    # region: us-east-1        # Optional, defaults to hub region
```

**KRO example** (`spoke-values/tenants/workshop/kro-clusters/values.yaml`):

```yaml
clusters:
  my-spoke:
    clusterName: my-spoke
    vpcCidr: "10.3.0.0/16"
    kubernetesVersion: "1.35"
    autoMode: true
    resourcePrefix: peeks
```

### Step 3: Register as a fleet member

Create `members/<cluster-name>/values.yaml` so ArgoCD creates a cluster secret and deploys addons:

```yaml
clusterName: my-spoke
labels:
  environment: dev       # or prod, staging
  tenant: workshop
```

## How It Works

1. **Provisioning**: The `clusters-crossplane` or `clusters-kro` ApplicationSet detects new entries in `spoke-values/` and creates the cloud infrastructure.
2. **Registration**: The `fleet-secrets` ApplicationSet detects entries in `members/` and creates ArgoCD cluster secrets.
3. **Addons**: The `cluster-addons` ApplicationSet detects new cluster secrets and deploys the configured addon stack.

> **Note**: Add the `members/` entry only after the cluster is provisioned (or simultaneously — ArgoCD will retry until the cluster is ready).
