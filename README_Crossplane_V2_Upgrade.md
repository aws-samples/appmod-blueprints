# Crossplane v1.17.1 → v2.0.2 Upgrade Guide

## Overview
This guide covers upgrading Crossplane from v1.17.1 to v2.0.2 across management, dev, and prod clusters managed by ArgoCD.

## Key Breaking Changes in v2.0.2
- `--enable-environment-configs` flag **removed** (causes crashes)
- CRD version alignment required (`storedVersions` vs `spec.versions`)
- Some CRDs need recreation due to version conflicts

## Pre-Upgrade: File Changes

### 1. Update Version Numbers
Update `targetRevision` from `1.17.1` to `2.0.2` in:
- `platform/infra/terraform/mgmt/terraform/templates/argocd-apps/crossplane.yaml` (line 15)
- `platform/infra/terraform/deploy-apps/manifests/crossplane-dev.yaml` (line 11)
- `platform/infra/terraform/deploy-apps/manifests/crossplane-prod.yaml` (line 11)

### 2. Remove Deprecated Flag
Comment out or remove `--enable-environment-configs` from:
- `packages/crossplane/dev/values.yaml`
- Change `args: [--enable-environment-configs]` to `args: []` in dev/prod manifests

## Upgrade Process

### Management Cluster (First)

1. **Apply File Changes & ArgoCD Refresh**
   ```bash
   kubectl patch application crossplane -n argocd --type='merge' -p='{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'
   ```

2. **Fix CRD Issues**
   ```bash
   # Delete problematic CRDs
   kubectl delete crd environmentconfigs.apiextensions.crossplane.io usages.apiextensions.crossplane.io
   
   # Delete crash-looping pod
   kubectl delete pod -n crossplane-system <crash-looping-pod-name>
   ```

3. **Verify Success**
   ```bash
   kubectl get pods -n crossplane-system
   # Should show Crossplane v2.0.2 running
   ```

### Dev & Prod Clusters (Remote)

**Issue**: ArgoCD applications have deprecated flag hardcoded in Helm values, causing continuous crashes.

#### Step 1: Disable ArgoCD Auto-Sync (Management Cluster)
```bash
# Disable auto-sync to prevent ArgoCD from reverting manual fixes
kubectl patch application crossplane-dev -n argocd --type='json' -p='[{"op": "remove", "path": "/spec/syncPolicy/automated"}]'
kubectl patch application crossplane-prod -n argocd --type='json' -p='[{"op": "remove", "path": "/spec/syncPolicy/automated"}]'
```

#### Step 2: Fix Each Remote Cluster

**For Dev Cluster:**
```bash
# Switch to dev cluster
# Delete problematic CRDs
kubectl delete crd environmentconfigs.apiextensions.crossplane.io usages.apiextensions.crossplane.io

# Manual deployment patch to remove deprecated flag
kubectl patch deployment crossplane -n crossplane-system --type='json' -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/args", "value": ["core", "start"]}]'

# Verify success
kubectl get pods -n crossplane-system
```

**For Prod Cluster:**
```bash
# Switch to prod cluster
# Delete problematic CRDs
kubectl delete crd environmentconfigs.apiextensions.crossplane.io usages.apiextensions.crossplane.io

# Manual deployment patch to remove deprecated flag
kubectl patch deployment crossplane -n crossplane-system --type='json' -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/args", "value": ["core", "start"]}]'

# Verify success
kubectl get pods -n crossplane-system
```

#### Step 3: Fix ArgoCD Application Sources (Management Cluster)
```bash
# Update Helm values to remove deprecated flag
kubectl patch application crossplane-dev -n argocd --type='json' -p='[{"op": "replace", "path": "/spec/source/helm/values", "value": "args: []\n"}]'
kubectl patch application crossplane-prod -n argocd --type='json' -p='[{"op": "replace", "path": "/spec/source/helm/values", "value": "args: []\n"}]'
```

#### Step 4: Re-enable ArgoCD Auto-Sync (Management Cluster)
```bash
# Re-enable auto-sync with correct configuration
kubectl patch application crossplane-dev -n argocd --type='json' -p='[{"op": "add", "path": "/spec/syncPolicy/automated", "value": {"selfHeal": true}}]'
kubectl patch application crossplane-prod -n argocd --type='json' -p='[{"op": "add", "path": "/spec/syncPolicy/automated", "value": {"selfHeal": true}}]'
```

## Verification

### Check All Clusters
```bash
# On each cluster
kubectl get pods -n crossplane-system
kubectl get crd | grep -E "(environmentconfigs|usages)"

# Should show:
# - Crossplane v2.0.2 pods running (1/1 Ready)
# - All providers updated and running
# - CRDs recreated with proper versions
```

### Check ArgoCD Applications (Management Cluster)
```bash
kubectl get applications -n argocd | grep crossplane
# Should show all as "Synced" and "Healthy"
```

## Troubleshooting

### Common Issues

1. **CrashLoopBackOff with "unknown flag --enable-environment-configs"**
   - **Cause**: Deprecated flag still in deployment args
   - **Fix**: Apply manual deployment patch or fix ArgoCD Helm values

2. **Init container fails with CRD version mismatch**
   - **Cause**: `storedVersions` doesn't match `spec.versions`
   - **Fix**: Delete problematic CRDs and let Crossplane recreate them

3. **ArgoCD keeps reverting manual patches**
   - **Cause**: Auto-sync enabled with wrong configuration
   - **Fix**: Disable auto-sync, fix source configuration, re-enable

### Emergency Rollback
If upgrade fails completely:
```bash
# Revert version in ArgoCD applications
kubectl patch application crossplane-dev -n argocd --type='json' -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "1.17.1"}]'
kubectl patch application crossplane-prod -n argocd --type='json' -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "1.17.1"}]'
```

## Success Criteria
- ✅ All clusters running Crossplane v2.0.2
- ✅ No crash-looping pods
- ✅ All providers updated and healthy
- ✅ ArgoCD applications synced and healthy
- ✅ CRDs properly aligned with correct versions

## In depth how to upgrade guide

### Prerequisites
- management cluster alias: engineering
- development cluster alias: dev
- production cluster alias: prod

### Step-by-Step Execution Order

#### Phase 1: ArgoCD UI Updates
1. **Update ArgoCD UI Application Manifests**:
    
    1. `argocd/crossplane` manifest changes:
        
        - `targetRevision`: 2.0.2 (formerly 1.17.1)
        - `targetRevision`: crossplane-version-upgrade (formerly main)
        - If repoURL for the git repo is missing the acutal link replace with `https://github.com/aws-samples/appmod-blueprints` manually
    2. argocd/crossplane-dev

        - `targetRevision`: 2.0.2 (formerly 1.17.1)
    3. argocd/crossplane-prod

        - `targetRevision`: 2.0.2 (formerly 1.17.1)
   

#### Phase 2: Management Cluster Upgrade
2. **Trigger upgrade**:
   ```bash
   kubectl patch application crossplane -n argocd --type='merge' -p='{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'
   ```

3. **Fix CRD issues** (when you see Init:CrashLoopBackOff):
   ```bash
   kubectl delete crd environmentconfigs.apiextensions.crossplane.io usages.apiextensions.crossplane.io
   kubectl delete pod <crash-looping-pod-name> -n crossplane-system
   ```

4. **Verify management cluster**:
   ```bash
   kubectl get pods -n crossplane-system  # All should be Running
   ```

#### Phase 3: Remote Clusters (Dev/Prod)
5. **Fix ArgoCD applications** (from management cluster):
   ```bash
   # Disable auto-sync
   kubectl patch application crossplane-dev -n argocd --type='json' -p='[{"op": "remove", "path": "/spec/syncPolicy/automated"}]'
   kubectl patch application crossplane-prod -n argocd --type='json' -p='[{"op": "remove", "path": "/spec/syncPolicy/automated"}]'
   
   # Fix Helm values
   kubectl patch application crossplane-dev -n argocd --type='json' -p='[{"op": "replace", "path": "/spec/source/helm/values", "value": "args: []\n"}]'
   kubectl patch application crossplane-prod -n argocd --type='json' -p='[{"op": "replace", "path": "/spec/source/helm/values", "value": "args: []\n"}]'
   
   # Re-enable auto-sync
   kubectl patch application crossplane-dev -n argocd --type='json' -p='[{"op": "add", "path": "/spec/syncPolicy/automated", "value": {"selfHeal": true}}]'
   kubectl patch application crossplane-prod -n argocd --type='json' -p='[{"op": "add", "path": "/spec/syncPolicy/automated", "value": {"selfHeal": true}}]'
   ```

6. **Switch to dev cluster and fix CRDs**:
   ```bash
   # Switch context to dev cluster
   kubectl delete crd environmentconfigs.apiextensions.crossplane.io usages.apiextensions.crossplane.io
   kubectl delete pod <crash-looping-pod-name> -n crossplane-system
   kubectl get pods -n crossplane-system  # Verify all Running
   ```

7. **Switch to prod cluster and fix CRDs**:
   ```bash
   # Switch context to prod cluster
   kubectl delete crd environmentconfigs.apiextensions.crossplane.io usages.apiextensions.crossplane.io
   kubectl delete pod <crash-looping-pod-name> -n crossplane-system
   kubectl get pods -n crossplane-system  # Verify all Running
   ```

#### Phase 4: Final Verification
8. **Check all ArgoCD applications** (from management cluster):
   ```bash
   kubectl get applications -n argocd | grep crossplane
   # All should show "Synced" and "Healthy"
   ```

### Critical Success Indicators
- ✅ No pods in CrashLoopBackOff state
- ✅ All Crossplane pods show image version v2.0.2
- ✅ ArgoCD applications show "Synced" and "Healthy"
- ✅ Providers are updating to newer versions

## Key Lessons
1. **ArgoCD Application specs** can override local file changes
2. **Disable auto-sync** when manual intervention is needed
3. **CRD cleanup** is often required for major version upgrades
4. **Test management cluster first** before touching remote clusters
5. **Always fix ArgoCD applications** to prevent future issues