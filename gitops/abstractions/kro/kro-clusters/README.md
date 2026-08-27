# KRO Clusters

Helm chart that renders `EksclusterWithVpc` KRO instances for provisioning EKS clusters via the KRO EKS Capability. This is an alternative to the Crossplane-based `abstractions/crossplane/platform-cluster/` — both can coexist on the same hub.

## How It Works

```
ApplicationSet (clusters-kro.yaml)
  └── Helm chart (kro-clusters/)
       └── Renders EksclusterWithVpc custom resources
            └── KRO ResourceGraphDefinition reconciles → ACK creates AWS resources
```

## Directory Structure

```
gitops/
├── bootstrap/
│   ├── clusters.yaml                    # ApplicationSet → Crossplane clusters
│   └── clusters-kro.yaml               # ApplicationSet → KRO clusters
├── addons/charts/
│   └── kro-clusters/                    # This chart
│       ├── Chart.yaml
│       └── templates/clusters.yaml      # Renders EksclusterWithVpc per entry
└── fleet/spoke-values/tenants/<tenant>/
    ├── kro-clusters/values.yaml         # Crossplane cluster definitions
    └── kro-clusters-kro/values.yaml     # KRO cluster definitions
```

## Usage

Add a cluster entry in `gitops/fleet/spoke-values/tenants/<tenant>/kro-clusters-kro/values.yaml`:

```yaml
clusters:
  spoke-test:
    tenant: workshop
    environment: dev
    region: us-west-2
    k8sVersion: "1.35"
    accountId: "123456789012"
    managementAccountId: "123456789012"
    resourcePrefix: peeks
    cidr:
      vpcCidr: "10.3.0.0/16"
      publicSubnet1Cidr: "10.3.1.0/24"
      publicSubnet2Cidr: "10.3.2.0/24"
      privateSubnet1Cidr: "10.3.11.0/24"
      privateSubnet2Cidr: "10.3.12.0/24"
```

Commit and push — ArgoCD will sync and KRO creates the cluster.

## Spec Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tenant` | string | `tenant1` | Tenant name for labeling |
| `environment` | string | `staging` | Environment (dev, staging, prod) |
| `region` | string | `us-west-2` | AWS region |
| `k8sVersion` | string | `1.34` | EKS Kubernetes version |
| `accountId` | string | (required) | AWS account ID for the cluster |
| `managementAccountId` | string | (required) | Management account ID |
| `adminRoleName` | string | `Admin` | IAM role name for cluster admin access |
| `domainName` | string | `""` | Domain name for ingress |
| `resourcePrefix` | string | `peeks` | Prefix for resource naming |
| `workloads` | string | `false` | Deploy workload applications |
| `cidr` | object | defaults | VPC/subnet CIDR configuration |
| `gitops` | object | defaults | GitOps repo URLs and revisions |
| `addons` | object | defaults | Addon enablement flags |

## Crossplane vs KRO — When to Use What

| | Crossplane | KRO |
|---|---|---|
| **Mechanism** | XRD + Composition + Upbound providers | ResourceGraphDefinition + ACK |
| **ApplicationSet** | `clusters.yaml` | `clusters-kro.yaml` |
| **Values path** | `kro-clusters/values.yaml` | `kro-clusters-kro/values.yaml` |
| **Best for** | Complex compositions, resource adoption, existing clusters | Simple provisioning, EKS Capability native |

Both approaches produce a fully functional EKS cluster with VPC, subnets, IAM roles, and Auto Mode enabled.

## Prerequisites

- KRO EKS Capability active on the hub cluster
- `eksclusterwithvpc.kro.run` ResourceGraphDefinition deployed and in `Active/Ready` state
- ACK controllers available (managed by EKS Capability)
