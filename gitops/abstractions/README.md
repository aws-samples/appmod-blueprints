# Abstractions

Crossplane Composite Resource Definitions (XRDs) and Compositions for provisioning fleet infrastructure. These are shared abstractions used by both the Kind bootstrap process and the hub's Crossplane instance.

## Directory Structure

```
abstractions/
└── resource-groups/
    └── platform-cluster/       Helm chart containing XRD + Composition
        ├── Chart.yaml
        ├── values.yaml          Default: no clusters (empty map)
        ├── templates/
        │   ├── xrd.yaml         PlatformCluster CRD definition
        │   └── composition.yaml What AWS resources to create
```

## PlatformCluster

A single claim that provisions a complete EKS cluster with all supporting infrastructure.

API: `platform.gitops.io/v1alpha1`
Claim kind: `PlatformCluster`
Composite kind: `XPlatformCluster`

### Spec Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `region` | string | (required) | AWS region |
| `clusterName` | string | (required) | Cluster name, also used as `crossplane.io/external-name` |
| `vpcCidr` | string | `10.0.0.0/16` | VPC CIDR block |
| `kubernetesVersion` | string | `1.32` | EKS Kubernetes version |
| `autoMode` | boolean | `true` | Enable EKS Auto Mode (managed compute, storage, networking) |
| `resourcePrefix` | string | | Prefix for resource tagging and identification |
| `managedNodeGroup.enabled` | boolean | `false` | Create a managed node group alongside Auto Mode |
| `managedNodeGroup.instanceTypes` | string[] | `["m5.large"]` | EC2 instance types for the node group |
| `managedNodeGroup.desiredSize` | integer | `2` | Desired number of nodes |
| `managedNodeGroup.minSize` | integer | `1` | Minimum number of nodes |
| `managedNodeGroup.maxSize` | integer | `5` | Maximum number of nodes |
| `managedNodeGroup.diskSize` | integer | `50` | Root volume size in GB |
| `managedNodeGroup.capacityType` | string | `ON_DEMAND` | `ON_DEMAND` or `SPOT` |

### Status Fields

| Field | Description |
|-------|-------------|
| `vpcId` | Provisioned VPC ID |
| `clusterEndpoint` | EKS API server endpoint |
| `oidcIssuer` | OIDC provider URL (for IRSA) |
| `nodeRoleArn` | IAM role ARN for Auto Mode nodes |

### What the Composition Provisions

A single `PlatformCluster` claim creates 20+ AWS resources:

**Networking**
- VPC with DNS support
- 2 public subnets (AZ a, b) with `kubernetes.io/role/elb` tags
- 2 private subnets (AZ a, b) with `kubernetes.io/role/internal-elb` tags
- Internet Gateway
- NAT Gateway + Elastic IP
- Public and private route tables with routes

**IAM**
- EKS cluster role with policies: EKSClusterPolicy, EKSComputePolicy, EKSNetworkingPolicy, EKSBlockStoragePolicy, EKSLoadBalancingPolicy
- EKS Auto Mode node role with policies: EKSWorkerNodeMinimalPolicy, EC2ContainerRegistryPullOnly

**EKS**
- EKS cluster with Auto Mode enabled (general-purpose + system node pools, block storage, elastic load balancing)
- Public and private API endpoint access
- Connection secret written to `crossplane-system`

**Conditional: Managed Node Group** (only when `managedNodeGroup.enabled: true`)
- MNG node IAM role with policies: EKSWorkerNodePolicy, EKS_CNI_Policy, EC2ContainerRegistryReadOnly
- MNG access entry (EC2_LINUX type)
- NodeGroup in private subnets with `workload=managednodes` taints (NoSchedule + NoExecute)
- EKS managed addons: vpc-cni, kube-proxy, coredns, eks-pod-identity-agent (required for MNG nodes, not needed by Auto Mode)

The conditional creation uses `function-cel-filter` in the composition pipeline. When `managedNodeGroup.enabled` is false or absent, the CEL filter removes all `mng-*`, `managed-nodegroup`, and `addon-*` resources from the desired state — no unnecessary AWS resources are created.

All resources use `matchControllerRef` for cross-referencing -- no manual wiring between resources.

## How It Is Used

### During Bootstrap (Kind)

The `kind-crossplane` provider applies the XRD and Composition directly to Kind, then applies `claims/hub-cluster.yaml` to create the hub's infrastructure.

### On the Hub (Fleet Clusters)

The `bootstrap/clusters.yaml` ApplicationSet deploys this chart as a Helm release to the hub. Values come from:

1. `fleet/kro-values/default/kro-clusters/values.yaml` -- default cluster definitions
2. `fleet/kro-values/tenants/<tenant>/kro-clusters/values.yaml` -- per-tenant overrides

The values file defines a `clusters` map:

```yaml
clusters:
  spoke-us-west-2:
    region: us-west-2
    clusterName: spoke-us-west-2
    vpcCidr: "10.1.0.0/16"
    kubernetesVersion: "1.32"
    autoMode: true
```

Each entry produces a `PlatformCluster` claim that Crossplane reconciles into AWS infrastructure.

## Resource Adoption

All claims use `crossplane.io/external-name` annotations to match existing AWS resources by name. This enables:

- **hub:update flow**: Spin up an ephemeral Kind cluster, apply claims, Crossplane adopts existing resources and reconciles the diff, then delete Kind.
- **Migration**: Move management of existing infrastructure to Crossplane without recreating resources.

The EKS cluster resource patches `clusterName` into `crossplane.io/external-name`, so the Crossplane-managed name always matches the actual AWS cluster name.
