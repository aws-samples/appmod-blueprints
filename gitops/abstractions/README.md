# Abstractions

Infrastructure abstractions for provisioning fleet clusters. Supports two engines — Crossplane and KRO — which can coexist on the same hub.

## Directory Structure

```
abstractions/
├── crossplane/
│   └── platform-cluster/       Helm chart containing XRD + Composition
│       ├── Chart.yaml
│       ├── values.yaml          Default: no clusters (empty map)
│       ├── templates/
│       │   ├── xrd.yaml         PlatformCluster CRD definition
│       │   └── composition.yaml What AWS resources to create
└── kro/
    └── kro-clusters/           Helm chart rendering EksclusterWithVpc instances
        ├── Chart.yaml
        ├── README.md
        └── templates/
            └── clusters.yaml    Renders KRO custom resources
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

## Which Clusters Get Each Crossplane Abstraction

`bootstrap/abstractions.yaml` installs each directory under `abstractions/crossplane/`
(its XRD and Composition) on every cluster whose ArgoCD cluster secret has that
abstraction's label. It works like addons: appmod defines the abstraction and its label,
and the consumer decides which clusters get it in its own `enabled-addons.yaml`.

| Directory | `enabled-addons.yaml` key | Cluster-secret label | Hub | Spokes |
|-----------|---------------------------|----------------------|-----|--------|
| `aws-resources` | `abstraction_aws_resources` | `enable_abstraction_aws_resources` | on | off |
| `platform-cluster` | `abstraction_platform_cluster` | `enable_abstraction_platform_cluster` | on | off |
| `pod-identity` | `abstraction_pod_identity` | `enable_abstraction_pod_identity` | on | off |

The hub defaults are set in `bootstrap/hub-fleet-secret.yaml` (`defaultEnabledAddons`),
not in an `enabled-addons.yaml`, so they apply even when the fleet repo is a consumer
repo. A consumer's `enabledAddons` always wins over them.

**To put PodIdentity on a spoke** (needed by the `aws-service-identity` OAM trait, which
creates a `PodIdentity` claim in the workload's own cluster), add this to that
environment's `gitops/overlays/environments/<env>/enabled-addons.yaml`:

```yaml
enabledAddons:
  abstraction_pod_identity: true
```

The spoke also needs what the pod-identity Composition uses: Crossplane with
`function-environment-configs` and `function-patch-and-transform`, `provider-aws-iam` and
`provider-aws-eks`, the `default` ProviderConfig, and the `env-config` EnvironmentConfig
(`clusterName`, `region`). These come from the `crossplane-base` and `env_config` registry
entries, which are both enabled by `crossplane: true`.

Leave `platform-cluster` off spokes: it provisions clusters and belongs on the hub.

**To turn an abstraction off**, set its key to `false`. The ApplicationSet never deletes
Applications (`applicationsSync: create-update`) and its template has no
`resources-finalizer`, because deleting an XRD deletes every claim of that kind (for
`platform-cluster`, the spoke clusters themselves). So after setting `false`, delete the
`<directory>-<cluster>` Application explicitly. The XRD and Composition stay on the
cluster; remove them by hand only once no claims of that kind remain.

**To add an abstraction**, add a generator for its directory in
`bootstrap/abstractions.yaml` and, if the hub should have it by default, a key in
`defaultEnabledAddons` in `bootstrap/hub-fleet-secret.yaml`. There is no wildcard, so a
new directory is installed nowhere until it has a label.

## How It Is Used

### During Bootstrap (Kind)

The `kind-crossplane` provider applies the XRD and Composition directly to Kind, then applies `claims/hub-cluster.yaml` to create the hub's infrastructure.

### On the Hub (Fleet Clusters)

The `bootstrap/clusters.yaml` ApplicationSet deploys this chart as a Helm release to the hub. Values come from:

1. `fleet/spoke-values/default/crossplane-clusters/values.yaml` -- default cluster definitions
2. `fleet/spoke-values/tenants/<tenant>/crossplane-clusters/values.yaml` -- per-tenant overrides

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
