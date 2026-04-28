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
     b. crossplane:providers      Render crossplane-base chart (providers + functions only, no ProviderConfig)
     c. crossplane:provider-config Apply bootstrap ProviderConfig (aws-credentials secret)
     d. crossplane:claims         Apply XRD/Composition, PlatformCluster claim, pod identities (see below)
  6. hub:seed
     a. Wait for EKS cluster, IAM roles, and pod identities to become Ready
     b. argocd:capability         Create EKS ArgoCD Capability via Job
     c. secrets-manager:seed      Write hub config to AWS Secrets Manager
     d. secrets-manager:seed-keycloak Seed keycloak passwords into Secrets Manager
     e. hub:install-eso           Helm install External Secrets on the hub
     f. hub:cluster-secret-store  Apply ClusterSecretStore for AWS Secrets Manager
     g. hub:seed-secret           Create the hub's ArgoCD cluster secret (with fleet_member: control-plane label)
     h. hub:apply-root-appset     Apply bootstrap/root-appset.yaml -- hub is now self-managing
```

After step 6h, the hub's ArgoCD syncs `bootstrap/` and takes over. Run `task destroy-kind` to remove the ephemeral Kind cluster.

## Crossplane Bootstrap and Hub Handover

### What bootstrap creates

The bootstrap uses the same Helm charts that run on the hub, ensuring consistent resource naming:

| Chart | Bootstrap flags | What it creates |
|-------|----------------|-----------------|
| `crossplane-base` | `providerConfig.enabled=false`, only iam+eks+ec2+family versions set, `createIdentity=false` for all | SAs, DRCs, functions, family+iam+eks+ec2 providers (no pod identities in this step) |
| `crossplane-base` (claims step) | iam+eks+ec2 with `createIdentity=true` (default) | IAM+EKS+EC2 roles + pod identities |
| `crossplane-pod-identity` | `identities.eso.enabled=true` | ESO IAM role + policy + pod identity only |

### What the hub manages (after ArgoCD takes over)

| Chart | Registry flags | What it creates | What it skips |
|-------|---------------|-----------------|---------------|
| `crossplane-base` | `createIdentity=false` for iam, eks, ec2 | ProviderConfig, SAs, DRCs, all providers | IAM+EKS+EC2 roles + pod identities (bootstrap-managed) |
| `aws-load-balancer-controller` | `additionalResources` → crossplane-pod-identity with `identities.lbc.enabled=true` | LBC role + policy + pod identity (wave -3 to -1), then LBC controller (wave 0) | — |
| `external-dns` | `additionalResources` → crossplane-pod-identity with `identities.external-dns.enabled=true` | external-dns role + policy + pod identity (wave -3 to -1), then external-dns controller (wave 0) | — |
| ESO pod identity | Not referenced by any hub addon | — | ESO role + policy + pod identity (bootstrap-permanent) |

### Why this split exists

PodIdentityAssociations use an opaque AWS-generated association ID as their external identifier. Crossplane can only adopt existing resources via `crossplane.io/external-name`, but the association ID is unknown until creation. When Kind is deleted, the Crossplane managed resources are lost but the AWS associations persist. If the hub tries to create new associations for the same (cluster, namespace, serviceAccount) combo, AWS returns 409 ResourceInUseException.

IAM Roles don't have this problem — they use human-readable names as external identifiers and are adopted cleanly via `crossplane.io/external-name`.

The solution: bootstrap-created pod identities (IAM, EKS, ESO) are permanent infrastructure. The hub's ArgoCD never attempts to recreate them.

## Claims

The `claims/` directory contains Crossplane resources applied directly to Kind during bootstrap:

| Claim | What it creates |
|-------|-----------------|
| `argocd-capability-role.yaml` | IAM role for the EKS ArgoCD Capability (trusted by `capabilities.eks.amazonaws.com`) |

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

## AWS Load Balancer Controller

The platform uses the open-source AWS Load Balancer Controller (LBC) instead of EKS Auto Mode's built-in ALB controller. This is required for features like URL rewrite (`alb.ingress.kubernetes.io/transforms.*`) which EKS Auto Mode silently ignores.

The `ingress-class-alb` chart supports both modes via the `controllerMode` value:

| Mode | Controller | IngressClassParams API | When to use |
|------|-----------|----------------------|-------------|
| `auto` (default) | `eks.amazonaws.com/alb` | `eks.amazonaws.com/v1` | EKS Auto Mode manages ALBs natively |
| `oss` | `ingress.k8s.aws/alb` | `elbv2.k8s.aws/v1beta1` | Need transforms, url-rewrite, or other OSS-only features |

The mode is controlled by the `alb_controller_mode` annotation on the ArgoCD cluster secret, set via `secrets-manager:seed`.

When using `oss` mode, the provider must also:
1. Set `enable_aws_load_balancer_controller: true` in `enabled-addons.yaml` (LBC pod identity is created automatically via `additionalResources`)
2. Include `aws_vpc_id` and `alb_controller_mode: oss` in the Secrets Manager seed metadata
4. Create the `aws-load-balancer-controller-sa` service account in `kube-system` on the hub
5. Add `alb.ingress.kubernetes.io/target-type: ip` to ingresses using ClusterIP services

## Spoke Cluster Provisioning

With the kind-crossplane provider, spoke clusters are provisioned by Crossplane on the hub. The hub's `bootstrap/clusters.yaml` ApplicationSet renders PlatformCluster claims from KRO values. The only manual step is seeding the spoke's connection credentials in Secrets Manager.

### Seed a spoke cluster's credentials

After the spoke's EKS cluster is ready (Crossplane has provisioned it), seed its connection details:

```bash
CLUSTER_NAME="spoke-us-west-2"
AWS_REGION="us-west-2"

# Wait for the cluster to be ready
aws eks wait cluster-active --name $CLUSTER_NAME --region $AWS_REGION

# Seed Secrets Manager
CLUSTER_ARN=$(aws eks describe-cluster --name $CLUSTER_NAME --region $AWS_REGION --query 'cluster.arn' --output text)
VPC_ID=$(aws eks describe-cluster --name $CLUSTER_NAME --region $AWS_REGION --query 'cluster.resourcesVpcConfig.vpcId' --output text)
SECRET_VALUE=$(jq -n \
  --arg server "$CLUSTER_ARN" \
  --arg config '{"tlsClientConfig":{"insecure":false}}' \
  --arg metadata "$(jq -n \
    --arg region "$AWS_REGION" \
    --arg cluster "$CLUSTER_NAME" \
    --arg vpc "$VPC_ID" \
    '{aws_region: $region, aws_cluster_name: $cluster, aws_vpc_id: $vpc}')" \
  '{metadata: $metadata, config: $config, server: $server}')
aws secretsmanager create-secret \
  --name "$CLUSTER_NAME/config" \
  --secret-string "$SECRET_VALUE" \
  --region $AWS_REGION 2>/dev/null \
|| aws secretsmanager put-secret-value \
  --secret-id "$CLUSTER_NAME/config" \
  --secret-string "$SECRET_VALUE" \
  --region $AWS_REGION
```

The spoke's Secrets Manager entry only contains cluster-specific values (ARN, region, name, VPC ID). Platform-wide values (repo URLs, domain, resourcePrefix) are sourced from the hub's cluster secret annotations — they don't need to be duplicated per spoke.
