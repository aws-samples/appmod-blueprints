# Kind + Crossplane Provider

Zero-Terraform bootstrap for the hub cluster. Spins up an ephemeral Kind cluster, installs Crossplane, provisions all AWS infrastructure (VPC, EKS, IAM), seeds ArgoCD on the hub, and then the Kind cluster can be deleted. The hub is fully self-managing from that point.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| kind | Local Kubernetes cluster |
| kubectl | Cluster access |
| helm 3.x | Chart installation |
| yq | YAML processing |
| aws CLI | Configured with credentials (local profile or EC2 instance profile) |
| `config.yaml` | Must have `hub.clusterName`, `aws.region`, `aws.accountId`, `repo.url` set |

## Task Commands

| Command | Description |
|---------|-------------|
| `task install` | Full bootstrap: Kind -> Crossplane -> AWS infra -> ArgoCD -> self-managing hub |
| `task status` | Show state of Kind, Helm releases, Crossplane providers, managed resources, ArgoCD apps |
| `task destroy-kind` | Delete the Kind cluster only (hub persists in AWS) |
| `task destroy` | Full teardown: delete Crossplane claims, wait for AWS resource cleanup, delete Kind |
| `task hub:update` | Update hub infrastructure using an ephemeral Kind cluster (see below) |
| `task credentials:refresh` | Force-refresh AWS credentials secret (use when tokens expire) |

## Bootstrap Flow

```
task install
  1. init              Verify CLIs exist
  2. kind:create       Create 3-node Kind cluster (1 control-plane, 2 workers)
  3. credentials:setup Create aws-credentials secret in crossplane-system
  4. argocd:install     Helm install ArgoCD (version from addons/registry/core.yaml)
  5. crossplane:setup
     a. crossplane:helm           Install Crossplane (version from addons/registry/platform.yaml)
     b. crossplane:providers      Apply AWS providers, wait for Healthy
     c. crossplane:provider-config Apply bootstrap ProviderConfig
     d. crossplane:claims         Apply XRD/Composition + all claims (see below)
  6. hub:seed
     a. Wait for EKS cluster, IAM roles, and pod identities to become Ready
     b. argocd:capability         Create EKS ArgoCD Capability via Job
     c. secrets-manager:seed      Write hub config to AWS Secrets Manager
     d. hub:install-eso           Helm install External Secrets on the hub
     e. hub:cluster-secret-store  Apply ClusterSecretStore for AWS Secrets Manager
     f. hub:seed-secret           Create the hub's ArgoCD cluster secret (with fleet_member: control-plane label)
     g. hub:apply-root-appset     Apply bootstrap/root-appset.yaml -- hub is now self-managing
```

After step 6g, the hub's ArgoCD syncs `bootstrap/` and takes over. Run `task destroy-kind` to remove the ephemeral Kind cluster.

## Crossplane Claims

All claims live in `claims/` and are applied to the Kind cluster during bootstrap. They create AWS resources that persist after Kind is deleted.

| Claim | Kind | What it creates |
|-------|------|-----------------|
| `hub-cluster.yaml` | PlatformCluster | VPC + subnets + IGW + NAT + EKS Auto Mode cluster (uses the shared XRD/Composition from `abstractions/`) |
| `argocd-capability-role.yaml` | Role | IAM role for the EKS ArgoCD Capability (trusted by `capabilities.eks.amazonaws.com`) |
| `eso-pod-identity-role.yaml` | Role + Policy + RolePolicyAttachment | IAM role with SecretsManager read/write access, for External Secrets Operator |
| `eso-pod-identity.yaml` | PodIdentityAssociation | Binds the ESO role to the `external-secrets-sa` service account in the hub |
| `crossplane-pod-identity-role.yaml` | Role + RolePolicyAttachment | IAM role with AdministratorAccess, for Crossplane on the hub |
| `crossplane-pod-identity.yaml` | PodIdentityAssociation | Binds the Crossplane role to the `provider-aws` service account in the hub |

## How hub:update Works

After initial bootstrap, the Kind cluster is deleted and hub infrastructure becomes unmanaged. To modify hub infrastructure later (e.g. change Kubernetes version, resize VPC):

1. Edit the relevant claim (e.g. `claims/hub-cluster.yaml`).
2. Run `task hub:update`.

This creates a new ephemeral Kind cluster, installs Crossplane, and applies all claims. Crossplane matches existing AWS resources via `crossplane.io/external-name` annotations and reconciles the diff rather than creating duplicates. Once the update converges, Kind is automatically deleted.

## Manifests

Supporting manifests in `manifests/`:

| Path | Purpose |
|------|---------|
| `argocd/create-capability.yaml` | Job that calls the EKS API to create the ArgoCD Capability |
| `argocd/appproject.yaml` | ArgoCD AppProject definition |
| `crossplane/provider-config-bootstrap.yaml` | ProviderConfig using the `aws-credentials` secret (Kind-only, not used on hub) |
| `external-secrets/cluster-secret-store.yaml` | ClusterSecretStore for AWS Secrets Manager |
