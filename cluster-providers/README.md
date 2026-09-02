# Cluster Providers

This directory contains pluggable cluster provisioning approaches. The addon management
system (charts, addons, overlays, fleet, bootstrap) is independent of how the hub
cluster is created.

## Available Providers

| Provider | Description | When to use |
|----------|-------------|-------------|
| `kind-crossplane/` | Kind + Crossplane (zero Terraform) | Greenfield, full GitOps |
| `byoc/` | Bring Your Own Cluster | Existing cluster, any cloud provider |

## The Contract

Any provider must produce a running hub cluster that satisfies the conditions below. Once met, the addon management system takes over — the provider's job is done.

### Inputs

| Source | Fields | Purpose |
|--------|--------|---------|
| `config.yaml` | `hub.clusterName`, `aws.region`, `aws.accountId` | Cluster identity |
| `config.yaml` | `repo.url`, `repo.revision`, `repo.basepath` | Git source for ArgoCD |
| `config.yaml` | `domain`, `resourcePrefix`, `ingressName` | Ingress and naming |
| `config.yaml` | `domainResolver` | Consumer command supplying an ingress hostname that does not exist yet at install time (e.g. a CloudFront distribution). See [docs/platform/domain-resolution-design.md](../docs/platform/domain-resolution-design.md) |
| `config.yaml` | `identityCenter.*`, `argocdCapability.*` | EKS ArgoCD Capability setup |
| `addons/registry/core.yaml` | `argocd.defaultVersion`, `external-secrets.defaultVersion` | Versions (no hardcoding) |
| AWS credentials | IAM permissions | EKS, VPC, IAM, Secrets Manager, Pod Identity |
| `bootstrap/root-appset.yaml` | ApplicationSet manifest | Applied as the final step |

### Outputs

When bootstrap completes, the following must exist:

#### AWS Resources

| Resource | Details |
|----------|---------|
| EKS cluster | Running, accessible via ARN |
| VPC + subnets | Networking for the cluster |
| IAM roles | ArgoCD capability role, ESO pod identity role, Crossplane pod identity role |
| Pod identity associations | ESO and Crossplane mapped to their IAM roles |
| Secrets Manager `<cluster>/config` | Cluster metadata: repo URLs, region, account ID, domain, ingress config |

#### Hub Cluster Resources

| Resource | Namespace | Details |
|----------|-----------|---------|
| ArgoCD | (managed) | EKS ArgoCD Capability running — no pods in `argocd` namespace |
| External Secrets Operator | `external-secrets` | Installed via Helm before ArgoCD can manage it (chicken-and-egg) |
| ClusterSecretStore `aws-secrets-manager` | cluster-scoped | ESO can read from Secrets Manager |
| Seed cluster secret `<cluster>` | `argocd` | See below |
| `root-appset.yaml` | `argocd` | Bootstrap ApplicationSet applied |

#### Seed Cluster Secret

The seed secret is intentionally minimal — just enough for the bootstrap ApplicationSet to target the hub. The fleet-secret chart enriches it later.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <clusterName>
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    fleet_member: control-plane
    environment: control-plane
  annotations:
    addonsRepoURL: <repo.url>
    addonsRepoRevision: <repo.revision>
    addonsRepoBasepath: <repo.basepath>
    fleetRepoURL: <repo.url>
    fleetRepoRevision: <repo.revision>
    fleetRepoBasepath: <repo.basepath>
stringData:
  name: <clusterName>
  server: <clusterARN>
  config: '{"tlsClientConfig":{"insecure":false}}'
```

What the seed secret does NOT have (added later by fleet-secret chart via ExternalSecret):
- `enable_*` labels (from `enabled-addons.yaml`)
- `tenant` label (from `fleet/members/<cluster>/values.yaml`)
- `aws_cluster_name`, `aws_region`, `ingress_domain_name`, `resource_prefix` annotations (from Secrets Manager `<cluster>/config`)

### Addon Secrets

Some addons require pre-seeded secrets in Secrets Manager. These are not part of the core contract — they are conditional on which addons are enabled in `enabled-addons.yaml`. If an addon is enabled and its chart expects a Secrets Manager entry, the provider must seed it during bootstrap.

| Addon | Secret Key | Required Properties | Purpose |
|-------|-----------|---------------------|---------|
| keycloak | `<cluster>/keycloak` | `keycloak_admin_password`, `keycloak_postgres_password`, `user_password` | Keycloak admin, database, and default user passwords |

Each addon's chart documents which Secrets Manager keys it expects — see the comment block at the top of the chart's secret template (e.g., `addons/charts/keycloak/templates/secret-gen.yaml`).

Providers should generate strong random passwords during bootstrap. The `kind-crossplane` provider does this in the `secrets-manager:seed-keycloak` task.

### The Handoff

Once `root-appset.yaml` is applied, ArgoCD takes over:

```
root-appset.yaml applied
  -> ArgoCD syncs bootstrap/
       -> addons.yaml       — renders appset-chart -> one ApplicationSet per addon
       -> fleet-secrets.yaml — discovers fleet/members/ -> fleet-secret chart enriches seed secret
       -> clusters.yaml     — KRO cluster provisioning (no-op until fleet members defined)
```

The fleet-secret chart reads `fleet/members/<cluster>/values.yaml` and `enabled-addons.yaml`, pulls full config from `<cluster>/config` in Secrets Manager, and overwrites the seed secret with the complete set of labels and annotations. From this point, addon ApplicationSets match clusters via `enable_*` labels and the system is fully self-managing.

The bootstrap cluster (Kind) is now disposable — `task destroy-kind` removes it.

### Taskfile Interface

The root `gitops/Taskfile.yaml` delegates to providers by name. Each provider
must expose these tasks in its `Taskfile.yaml`:

| Task | Required | Description |
|------|----------|-------------|
| `install` | Yes | Full bootstrap: create cluster, install ArgoCD, apply root-appset |
| `status` | Yes | Show current state of cluster, apps, and managed resources |
| `destroy` | Yes | Full teardown: remove cluster and clean up all resources |
| `destroy-kind` | No | Remove ephemeral bootstrap cluster only (hub persists) |
| `hub:update` | No | Update hub infrastructure without full reinstall |
| `init` | No | Verify prerequisites (CLIs, credentials, config) |

The root Taskfile calls these as `<provider-name>:install`, etc.

### Domain resolution (required behaviour, not a task)

A provider must resolve the ingress hostname **between its domain-independent and
domain-dependent work**, not at the start of `install`. Resolution order is `domain` in
config, then `domainResolver`, then fail; a provider must never deploy with an empty
domain. Both shipped providers implement this as `hub:seed-infra` → `domain:resolve` →
`hub:seed-platform`, with the second phase run as a **nested `task` process** because
go-task evaluates global `vars:` only once, at parse time.

Placing resolution late is what lets a consumer provision an asynchronously-created
hostname (typically CloudFront, 5–15 min) in parallel with the ~20 min cluster build.

Full rationale, the resolver contract, and the traps involved:
[docs/platform/domain-resolution-design.md](../docs/platform/domain-resolution-design.md).

### Capability parity (binding)

Providers are interchangeable behind one `config.yaml`, so **a capability added to one
provider must be added to all of them**. Where that is not yet true, the lacking provider
must **fail fast** with a clear message rather than silently ignore the input — a silently
ignored field means `config.local.yaml` means different things depending on
`clusterProvider`.

Current known gap: `kind-crossplane` cannot provision the hub into a pre-existing VPC, so
it rejects `hub.network.vpcId` in pre-flight
([#833](https://github.com/aws-samples/appmod-blueprints/issues/833)). `kind-kro-ack`
supports it.

### Configuration

Providers read shared configuration from `gitops/config.yaml`:

| Field | Description |
|-------|-------------|
| `clusterProvider` | Which provider to use (matches directory name) |
| `repo.url` | Git repository URL |
| `repo.revision` | Branch or tag |
| `repo.basepath` | Path prefix in the repo |
| `hub.clusterName` | Hub cluster name |
| `hub.kubernetesVersion` | Kubernetes version |
| `hub.network.vpcId`, `hub.network.subnetIds` | Optional: provision the hub into an existing VPC instead of creating one. Only `subnetIds[0]` and `[1]` are read. Supported by `kind-kro-ack`; `kind-crossplane` fails fast (see above) |
| `aws.region` | AWS region |
| `aws.accountId` | AWS account ID |
| `domain` | Base domain for ingress. May be empty only when `domainResolver` is set |
| `domainResolver` | Command that blocks until the ingress hostname is known and prints it |
| `insecure` | ALB serves plain HTTP (consumer terminates TLS upstream, e.g. CloudFront) |
| `identityCenter.*` | AWS Identity Center config (for EKS ArgoCD Capability) |
| `argocdCapability.*` | ArgoCD capability config |

Provider-specific config (e.g., Kind node count, VPC CIDR) can live in the
provider's own directory but should not duplicate values from `config.yaml`.

### AWS credential resolution (EC2 vs local) — kubectl implications

The provider Taskfiles export `AWS_PROFILE` (from `aws.profile`, default `"default"`)
to every `aws`/`kubectl`/`helm` call so local multi-account users get consistent
credential targeting. On an EC2 instance authenticated by an **instance role**,
there is usually no `[default]` profile in `~/.aws/config`, so a bare
`AWS_PROFILE=default` fails (`config profile (default) could not be found`) and the
credential chain never falls through to IMDS.

To keep `AWS_PROFILE` flowing while still resolving on EC2, the Taskfiles set
`AWS_CONFIG_FILE`: on an EC2 host they generate `private/aws-config` containing
`[default]\ncredential_source = Ec2InstanceMetadata` and point `AWS_CONFIG_FILE`
at it; off-instance they fall back to the user's existing `AWS_CONFIG_FILE` or
`~/.aws/config` (unchanged behavior).

> **⚠️ kubectl outside `task` on EC2.** `aws eks update-kubeconfig` bakes the
> active `AWS_PROFILE` (`default`) into the kubeconfig's exec block. That profile
> only resolves when `AWS_CONFIG_FILE` points at the generated config — which the
> Taskfiles set, but your interactive shell does not. So `kubectl` run directly
> (outside `task`) on an EC2 host will fail with
> `config profile (default) could not be found` / `exec: executable aws failed`.
> Fix with **either**:
> - export the generated config for your shell:
>   `export AWS_CONFIG_FILE=<repo>/.platform/private/aws-config`, **or**
> - regenerate the kubeconfig without a profile so it uses the instance role:
>   `env -u AWS_PROFILE aws eks update-kubeconfig --name <hub> --region <region>`

## Adding a New Provider

1. Create a directory under `cluster-providers/` matching the provider name
2. Add a `Taskfile.yaml` exposing at minimum: `install`, `status`, `destroy`
3. Add a `README.md` explaining the approach
4. Register the include in `gitops/Taskfile.yaml`:
   ```yaml
   includes:
     my-provider:
       taskfile: ./cluster-providers/my-provider/Taskfile.yaml
       dir: ./cluster-providers/my-provider
       optional: true
   ```
5. Set `clusterProvider: "my-provider"` in `config.yaml` to use it
