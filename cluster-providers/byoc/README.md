# Bring Your Own Cluster (BYOC)

Use this provider when you already have an EKS cluster with ArgoCD installed.
The BYOC provider handles everything from External Secrets Operator onward --
it does not provision infrastructure or install ArgoCD.

## Prerequisites

- An EKS cluster with ArgoCD installed and running
- `kubectl` configured to access the cluster
- `helm` 3.x installed
- `yq` installed
- AWS CLI configured with credentials that can access Secrets Manager
- AWS IAM role for External Secrets (e.g., IRSA or Pod Identity) to read from Secrets Manager

## Quick Start

### 1. Configure

Edit `config.yaml` in the repository root:

```yaml
clusterProvider: "byoc"

repo:
  url: "https://github.com/YOUR_ORG/YOUR_REPO.git"
  revision: "main"
  basepath: "gitops/"

hub:
  clusterName: "your-cluster-name"

aws:
  region: "us-west-2"
  accountId: "123456789012"
```

### 2. Validate

```bash
task validate
```

This checks CLI tools, config.yaml fields, cluster connectivity, and ArgoCD health.

### 3. Install

```bash
task install
```

This runs the full bootstrap sequence:

1. Validates prerequisites
2. Seeds cluster config into AWS Secrets Manager
3. Installs External Secrets Operator on the hub
4. Applies a ClusterSecretStore for AWS Secrets Manager
5. Creates the minimal seed cluster secret (repo coordinates + fleet labels)
6. Applies the root ApplicationSet to start the addon pipeline

### 4. Verify

```bash
task status
```

You should see `cluster-addons`, `fleet-secrets`, and `clusters` ApplicationSets,
and Applications being created for each enabled addon.

## Available Tasks

| Task | Description |
|------|-------------|
| `task validate` | Pre-flight checks (CLIs, config, cluster, ArgoCD) |
| `task install` | Full bootstrap sequence |
| `task status` | Show ArgoCD apps and ESO health |
| `task destroy` | Guidance for manual teardown |

## What Happens Next

1. `fleet-secrets` reads `fleet/members/hub/values.yaml` + `overlays/environments/control-plane/enabled-addons.yaml`
2. The fleet-secret chart generates a new cluster secret with `enable_*` labels
3. `cluster-addons` renders the appset-chart with registry domain files
4. ApplicationSets match the `enable_*` labels and create Applications per addon
5. ArgoCD syncs each addon to the hub cluster

## Customization

- Edit `overlays/environments/control-plane/enabled-addons.yaml` to enable/disable addons
- Edit `fleet/members/hub/values.yaml` to change cluster annotations
- Edit `addons/registry/*.yaml` to add/modify addon definitions

## Spoke Cluster Provisioning

With BYOC, spoke clusters are provisioned externally (console, CLI, Terraform, etc.). The hub's ArgoCD manages addon deployment to spokes, but does not create the clusters themselves. You need to seed each spoke's connection credentials in Secrets Manager so the fleet-secret ExternalSecret can produce an ArgoCD cluster secret.

### Seed a spoke cluster's credentials

```bash
CLUSTER_NAME="spoke-us-west-2"
AWS_REGION="us-west-2"

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

Then register the spoke as a fleet member (see [main README](../../README.md#add-a-new-fleet-member-cluster) for the GitOps steps).
