# Terraform Deployment Guide

## Prerequisites

- AWS CLI (2.17+)
- kubectl (1.30+)
- Terraform (1.5+)
- jq, git, yq, curl

### Required Environment Variables

Set these before running deployment scripts:

```bash
export RESOURCE_PREFIX="peeks"           # Resource naming prefix
export AWS_REGION="us-west-2"            # AWS region
export TFSTATE_BUCKET_NAME="<bucket>"    # S3 backend bucket - update this to uniq bucket name
export USER1_PASSWORD="your-password"    # User password (or IDE_PASSWORD from CloudFormation)
export HUB_VPC_ID="vpc-xxxxx"           # Hub cluster VPC ID
export HUB_SUBNET_IDS='["subnet-xxx"]'  # Hub cluster subnet IDs
```

**Note:** When using CloudFormation bootstrap, `IDE_PASSWORD` is automatically set and used as `USER1_PASSWORD`. This password is used for:
- ArgoCD admin access
- Keycloak test users (user1, user2)
- GitLab authentication

## Configuration

### Cluster Configuration

Edit `platform/infra/terraform/hub-config.yaml` to configure clusters and addons before deployment:

```yaml
clusters:
  hub:
    name: hub
    region: us-west-2
    environment: control-plane
    addons:
      enable_argocd: true
      enable_keycloak: true
      enable_backstage: true
      # Add more addon flags as needed
```

## Deployment Architecture

The platform uses a two-phase deployment approach:

1. **Phase 1: Cluster Infrastructure** - Creates EKS clusters (hub, dev, prod)
2. **Phase 2: Platform Addons** - Deploys GitOps controllers and platform services

> **⚠️ IMPORTANT: Always use deployment scripts, never run terraform commands directly**
>
> Each Terraform stack has dedicated `deploy.sh` and `destroy.sh` scripts that handle:
> - Environment variable setup and validation
> - Backend configuration and initialization
> - State management and locking
> - Error handling and cleanup
> - Workspace management for multi-cluster deployments

## Quick Start

### Step 1: Deploy Cluster Infrastructure

Creates hub cluster (control-plane) and spoke clusters (dev, prod):

```bash
cd platform/infra/terraform/cluster
./deploy.sh
```

**What this creates:**
- Hub cluster with control-plane environment
- Dev spoke cluster for development workloads
- Prod spoke cluster for production workloads
- VPC and networking for each cluster
- EKS node groups with auto-scaling

**Duration:** ~20-30 minutes

### Step 2: Deploy Platform Addons

Deploys GitOps controllers and platform services to all clusters:

```bash
cd platform/infra/terraform/common
./deploy.sh
```

**What this creates:**
- **Hub Cluster:** ArgoCD, Backstage, Keycloak, External Secrets, Ingress
- **All Clusters:** ACK controllers, Pod Identity associations, External Secrets integration

**Duration:** ~15-20 minutes

### Step 3: Initialize Platform Services

After addon deployment, initialize and sync ArgoCD applications:

```bash
cd platform/infra/terraform/scripts
./0-init.sh
```

This script:
- Verifies cluster readiness
- Syncs ArgoCD applications
- Waits for platform services to become healthy
- Configures Backstage integration

**Duration:** ~10-15 minutes

### Step 4: Access Platform Services

Platform services are exposed via CloudFront. Get URLs and credentials:

```bash
cd platform/infra/terraform/scripts
./1-tools-urls.sh
```

This displays:
- **ArgoCD:** `admin / $USER1_PASSWORD`
- **Keycloak:** `admin / <keycloak-admin-password>`
- **Backstage:** `user1 / $USER1_PASSWORD`
- **Argo Workflows:** `user1 / $USER1_PASSWORD`
- **Kargo:** `user1 / $USER1_PASSWORD`
- **GitLab:** `user1 / $USER1_PASSWORD`

### Manual Password Retrieval

If needed, retrieve passwords directly:

```bash
# Keycloak admin password
kubectl get secrets -n keycloak keycloak-config -o jsonpath='{.data.KEYCLOAK_ADMIN_PASSWORD}' | base64 -d
```

## GitOps Workflow

After deployment, ArgoCD automatically manages applications based on Git configurations:

```
Git Commit → ArgoCD Sync → Kubernetes Apply → Application Running
```

**Key GitOps Directories:**
- `gitops/addons/` - Platform services and addons
- `gitops/workloads/` - Application deployments
- `gitops/fleet/` - Multi-cluster management

## Troubleshooting

### Check Deployment Status

```bash
# View ArgoCD applications
kubectl get applications -n argocd

# Check addon sync status
kubectl get applications -n argocd -l app.kubernetes.io/instance=addons

# View pod status
kubectl get pods -A
```

### Common Issues

**ApplicationSet not generating Applications:**
- Verify cluster secret labels: `kubectl get secret -n argocd -o yaml | grep enable_`
- Check addon enablement in `hub-config.yaml`
- Review ApplicationSet status: `kubectl describe applicationset addons -n argocd`

**Addon stuck in sync:**
- Check sync wave dependencies
- Review Application events: `kubectl describe application <app-name> -n argocd`
- View ArgoCD logs: `kubectl logs -n argocd deployment/argocd-application-controller`

## Advanced Configuration

### Adding New Addons

See the comprehensive guide in the platform documentation for adding new addons to the GitOps system.

### Multi-Cluster Management

Add new clusters by updating `hub-config.yaml` and running both deployment scripts.

## Cleanup

Always destroy resources in reverse order:

```bash
# 1. Destroy platform addons
cd platform/infra/terraform/common
./destroy.sh

# 2. Destroy clusters
cd platform/infra/terraform/cluster
./destroy.sh
```

**Note:** S3 state buckets are preserved to prevent accidental data loss. Manually delete if needed.
