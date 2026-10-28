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
    k8sVersion: "1.37"
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
| `k8sVersion` | string | `1.37` | EKS Kubernetes version |
| `accountId` | string | (required) | AWS account ID for the cluster |
| `managementAccountId` | string | (required) | Management account ID |
| `adminRoleName` | string | `Admin` | IAM role name for cluster admin access |
| `domainName` | string | `""` | Domain name for ingress |
| `resourcePrefix` | string | `peeks` | Prefix for resource naming |
| `workloads` | string | `false` | Deploy workload applications |
| `cidr` | object | defaults | VPC/subnet CIDR configuration |
| `gitops` | object | defaults | GitOps repo URLs and revisions |
| `addons` | object | defaults | Addon enablement flags |

## ACK CARM coverage (`manageIamRoleSelectors`)

The EKS-managed ACK capability chooses its per-service workload role
(`<prefix>-cluster-mgmt-<svc>`) **per namespace** from an `IAMRoleSelector`. Each spoke's
ACK CRs live in namespace `<cluster name>`; if no selector covers it, ACK falls back to the
capability's own minimal role and every create is denied (e.g. `403 ec2:CreateVpc`).

By default this chart renders **no** selector: the workshop covers its spokes through the
`multi-acct` chart (`configs/multi-acct/values.yaml`, written by `task spokes:enable-kro`),
and on the direct path `multi-acct` reads the `spoke_namespaces` hub annotation
(`global.spokeNames`). Both are lists kept in sync by hand with the cluster keys here.

Set `manageIamRoleSelectors: true` once, at the top of the tenant `kro-clusters/values.yaml`,
to have this chart render the 8 selectors (`ec2 eks iam ecr s3 dynamodb secretsmanager rds`)
for every spoke **from its own name** — coverage can then never drift from the spoke set.

```yaml
manageIamRoleSelectors: true      # every spoke below gets CARM coverage
clusters:
  peeks-a-dev: {}                 # same account -> inherits global.accountId
  other-acct:
    accountId: "<account-id>"     # cross-account -> role in that account
  covered-elsewhere:
    manageIamRoleSelectors: false # still covered via configs/multi-acct
```

- Names/spec are identical to `multi-acct`'s (`<svc>-<name>`); the hub prefix and account are
  inherited (`global.resourcePrefix`, `global.accountId`), never hardcoded.
- **Do not also list an enabled spoke in `spoke_namespaces` or `configs/multi-acct`.** ACK
  refuses a resource matched by more than one selector. (Because names are identical and the
  CRD is cluster-scoped, an accidental double declaration collapses onto one object — an
  Argo CD `SharedResourceWarning` — rather than breaking reconciliation.)
- Selectors carry `Delete=false`: they must outlive the spoke's ACK CRs during
  `argocd app delete --cascade`. Delete them once the spoke namespace is gone.

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
