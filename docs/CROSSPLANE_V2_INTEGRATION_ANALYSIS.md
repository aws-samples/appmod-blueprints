# Crossplane V2 Integration Analysis

## Project Overview

This is the **Platform Engineering on Amazon EKS** workshop repository. It provides:
- Multi-cluster EKS deployment (hub + spoke architecture)
- GitOps-based addon management via ArgoCD
- Crossplane for cloud resource provisioning
- Backstage developer portal
- Various platform tools (Keycloak, Grafana, etc.)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CloudFormation Stack                          │
│  (peeks-workshop.json - downloads and deploys this repo)        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Terraform Deployment                          │
│  platform/infra/terraform/cluster/  - EKS clusters              │
│  platform/infra/terraform/common/   - Addons & ArgoCD           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ArgoCD ApplicationSets                        │
│  gitops/addons/bootstrap/default/addons.yaml                    │
│  (Defines all addon configurations including Crossplane)        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Crossplane Components                         │
│  gitops/addons/charts/crossplane-aws/  - Helm chart             │
│  gitops/addons/default/addons/crossplane/  - Values             │
│  gitops/addons/default/addons/crossplane-aws/  - AWS config     │
└─────────────────────────────────────────────────────────────────┘
```

## Key Files for Crossplane Configuration

| File | Purpose |
|------|---------|
| `gitops/addons/bootstrap/default/addons.yaml` | ArgoCD ApplicationSet definitions - **contains `--enable-environment-configs` flag** |
| `gitops/addons/charts/crossplane-aws/Chart.yaml` | Crossplane AWS chart - shows appVersion `1.17.1` |
| `gitops/addons/charts/crossplane-aws/templates/providers.yaml` | AWS provider definitions (S3, DynamoDB, RDS, EC2, etc.) |
| `gitops/addons/charts/crossplane-aws/templates/compositions.yaml` | Composition definitions (S3, DynamoDB, RDS) |
| `gitops/addons/default/addons/crossplane/values.yaml` | Crossplane core Helm values |
| `gitops/addons/default/addons/crossplane-aws/values.yaml` | AWS provider versions |

## Current State (v1.17.1)

- Crossplane version: `1.17.1`
- Uses `--enable-environment-configs` flag (line 1136 in addons.yaml)
- Compositions use "Resources" mode (not Pipeline mode)
- No `function-patch-and-transform` installed
- EC2 provider already defined in providers.yaml

## Required Changes for V2 Upgrade

### 1. Remove `--enable-environment-configs` Flag
**File**: `gitops/addons/bootstrap/default/addons.yaml` (line ~1136)

**Current**:
```yaml
args: ['--enable-environment-configs']
```

**Change to**:
```yaml
args: []
```

**Reason**: This flag was removed in Crossplane v2.0.0 - environment configs are now enabled by default.

### 2. Update Crossplane Version
**File**: `gitops/addons/bootstrap/default/addons.yaml` (line ~1124)

**Current**:
```yaml
defaultVersion: '1.17.1'
```

**Change to**:
```yaml
defaultVersion: '2.0.2'
```

### 3. Update Chart appVersion
**File**: `gitops/addons/charts/crossplane-aws/Chart.yaml`

**Current**:
```yaml
appVersion: "1.17.1"
```

**Change to**:
```yaml
appVersion: "2.0.2"
```

### 4. Add function-patch-and-transform
**File**: `gitops/addons/charts/crossplane-aws/templates/functions.yaml` (NEW FILE)

```yaml
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-patch-and-transform
  annotations:
    argocd.argoproj.io/sync-wave: "15"
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-patch-and-transform:v0.2.1
```

### 5. Update Compositions to Pipeline Mode
The compositions in `gitops/addons/charts/crossplane-aws/templates/compositions.yaml` need to be updated to use Pipeline mode with `function-patch-and-transform`. This is a larger change that involves restructuring the composition specs.

## Provider Configuration (Already Correct)

The following are already properly configured in `gitops/addons/default/addons/crossplane-aws/values.yaml`:
- EC2 provider: `v1.13.1` ✓
- RDS provider: `v1.13.1` ✓
- S3 provider: `v1.14.0` ✓
- DynamoDB provider: `v1.13.1` ✓
- IAM provider: `v1.13.1` ✓

## Deployment Flow

1. CloudFormation deploys infrastructure + IDE
2. CodeBuild runs Terraform scripts
3. Terraform creates EKS clusters
4. Terraform bootstraps ArgoCD
5. ArgoCD deploys addons from `gitops/addons/bootstrap/default/addons.yaml`
6. Crossplane addon is deployed with configured version and args
7. Crossplane-aws addon deploys providers and compositions

## Summary of Changes Needed

| Priority | File | Change |
|----------|------|--------|
| **P0** | `gitops/addons/bootstrap/default/addons.yaml` | Remove `--enable-environment-configs` flag |
| **P0** | `gitops/addons/bootstrap/default/addons.yaml` | Update `defaultVersion` to `2.0.2` |
| **P1** | `gitops/addons/charts/crossplane-aws/Chart.yaml` | Update `appVersion` to `2.0.2` |
| **P1** | `gitops/addons/charts/crossplane-aws/templates/functions.yaml` | Add function-patch-and-transform (NEW) |
| **P2** | `gitops/addons/charts/crossplane-aws/templates/compositions.yaml` | Update to Pipeline mode (if using new compositions) |
