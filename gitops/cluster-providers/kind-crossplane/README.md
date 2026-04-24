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
     d. secrets-manager:seed-keycloak Seed keycloak passwords into Secrets Manager
     e. hub:install-eso           Helm install External Secrets on the hub
     f. hub:cluster-secret-store  Apply ClusterSecretStore for AWS Secrets Manager
     g. hub:seed-secret           Create the hub's ArgoCD cluster secret (with fleet_member: control-plane label)
     h. hub:apply-root-appset     Apply bootstrap/root-appset.yaml -- hub is now self-managing
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
| `lbc-pod-identity-role.yaml` | Role + Policy + RolePolicyAttachment | IAM role with ELB/EC2/WAF/Shield/ACM permissions, for AWS Load Balancer Controller |
| `lbc-pod-identity.yaml` | PodIdentityAssociation | Binds the LBC role to the `aws-load-balancer-controller-sa` service account in the hub |

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
1. Create the LBC IAM role + policy via Crossplane claims (`lbc-pod-identity-role.yaml`, `lbc-pod-identity.yaml`)
2. Set `enable_aws_load_balancer_controller: true` in `enabled-addons.yaml`
3. Include `aws_vpc_id` and `alb_controller_mode: oss` in the Secrets Manager seed metadata
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
