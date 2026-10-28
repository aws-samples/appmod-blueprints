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

## ACK CARM coverage (IAMRoleSelectors)

The EKS-managed ACK capability chooses its per-service workload role
(`<prefix>-cluster-mgmt-<svc>`) **per namespace** from an `IAMRoleSelector`. Each spoke's
ACK CRs live in namespace `<cluster name>`; if no selector covers it, ACK falls back to the
capability's own minimal role and every create is denied (e.g. `403 ec2:CreateVpc`).

This chart is the **only** place spoke coverage is declared. For every entry under `clusters:`
it renders, from the entry itself and with no opt-in:

- the `Namespace` `<name>` (annotation `services.k8s.aws/team-id: <name>`);
- 8 `IAMRoleSelector`s `<svc>-<name>` for `ec2 eks iam ecr s3 dynamodb secretsmanager rds`,
  ARN `arn:aws:iam::<accountId>:role/<hub prefix>-cluster-mgmt-<svc>`.

A spoke therefore cannot exist without its selectors, and there is nothing to keep in sync by
hand. The account is the entry's `accountId` (cross-account spoke) or else `global.accountId`
(the hub's account, threaded by `clusters-kro`); the prefix is the hub's
`global.resourcePrefix`. Neither is ever hardcoded in a values file.

| Object | Owner (Argo CD Application) |
|---|---|
| `Namespace <spoke>`, `IAMRoleSelector <svc>-<spoke>` | `clusters-kro-<spoke>` (this chart) |
| `Namespace <hub>`, `IAMRoleSelector <svc>-<hub>` | `multi-acct-<hub>` (`gitops/addons/charts/multi-acct`) |

- A spoke declared with the hub's name **fails to render** (the hub's objects belong to
  `multi-acct`); `clusters-kro` passes the hub's name as `global.hubClusterName`.
- `multi-acct` ignores every `configs/multi-acct/values.yaml` `clusters:` key except the hub's
  own (an account override for the hub), so a legacy spoke entry there is never a second owner.
- All objects carry `Prune=false,Delete=false`: they must outlive the spoke's ACK CRs during
  the deliberate `argocd app sync clusters-kro-<name> --prune` (`spokes:disable-kro`) or an
  `argocd app delete --cascade`. `spokes:sweep-kro` deletes the namespace, then the selectors.
- Adding an ACK service means adding it to **both** service lists (this chart and
  `multi-acct`); `workshop/scripts/tests/test_carm_single_owner.py` fails if they differ.

### Migration (fleet repos created before this chart owned the selectors)

Before, `multi-acct` rendered the spoke objects from `configs/multi-acct/values.yaml`
(written by `spokes:enable-kro`, by the Backstage EKS template, or by hand). After the
upgrade the same objects, with the **same names and specs**, are rendered here instead. They
are handed over without ever being deleted:

1. `multi-acct-<hub>` stops rendering them. Its automated sync runs with `prune: false`
   (`gitops/addons/registry/_defaults.yaml`), so Argo CD only marks them "requires pruning"
   and leaves them live.
2. The next sync of `clusters-kro-<spoke>` applies the same objects. Argo CD (annotation
   tracking) finds the live object for each target, applies it and rewrites its
   `argocd.argoproj.io/tracking-id` to `clusters-kro-<spoke>`; from then on `multi-acct` no
   longer considers it its own. The spec does not change, so ACK's selector cache sees an
   update, never a delete, and the spoke's CRs keep their role throughout.
3. If `clusters-kro-<spoke>` syncs first, both Applications briefly render the object (a
   `SharedResourceWarning`, same spec); it settles as soon as `multi-acct` reads the new revision.

Do **not** run `argocd app sync multi-acct-<hub> --prune` during the upgrade, before every
spoke object shows the `clusters-kro-<spoke>` tracking id:

```bash
kubectl get iamroleselectors.services.k8s.aws,namespaces \
  -o custom-columns='NAME:.metadata.name,OWNER:.metadata.annotations.argocd\.argoproj\.io/tracking-id'
```

Afterwards the `clusters:` spoke entries in `configs/multi-acct/values.yaml` can be deleted
(optional; they are ignored). A legacy entry for a namespace that is **not** a kro-clusters
spoke is no longer rendered: its live objects stay (prune is off) but are no longer managed.

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
