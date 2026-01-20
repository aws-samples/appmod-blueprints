# Custom NodePool Migration Guide

## Overview

This guide explains how to migrate from EKS Auto Mode default nodepools to custom PEEKS-managed nodepools with less aggressive consolidation settings.

## Default vs Custom NodePools

### EKS Auto Mode Defaults
- **general-purpose**: `consolidateAfter: 30s` (very aggressive)
- **system**: `consolidateAfter: 30s` (very aggressive)
- **gpu**: `consolidateAfter: 1h` (reasonable)

### PEEKS Custom NodePools
- **peeks-general-purpose**: `consolidateAfter: 10m` (balanced)
- **peeks-system**: `consolidateAfter: 30m` (stable)
- **gpu**: Keep existing (already has good settings)

## Key Differences

### peeks-general-purpose
```yaml
consolidateAfter: 10m                    # vs 30s default
consolidationPolicy: WhenEmptyOrUnderutilized
terminationGracePeriod: 48h              # vs 24h default
labels:
  managed-by: peeks                      # Easy identification
```

### peeks-system
```yaml
consolidateAfter: 30m                    # vs 30s default
consolidationPolicy: WhenEmpty           # Only when completely empty
terminationGracePeriod: 48h
taints:
  - key: CriticalAddonsOnly
    effect: NoSchedule
```

## Migration Steps

### Step 1: Enable Custom NodePools

Update the platform-manifests values:

```bash
# Edit the values file
vim gitops/addons/bootstrap/default/addons/platform-manifests/values.yaml

# Change:
customNodepools:
  enabled: true  # Changed from false
```

Commit and push:
```bash
git add gitops/addons/bootstrap/default/addons/platform-manifests/values.yaml
git commit -m "Enable custom PEEKS nodepools"
git push
```

Sync ArgoCD:
```bash
kubectl patch application platform-manifests-peeks-hub -n argocd --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### Step 2: Verify Custom NodePools Created

```bash
kubectl get nodepools
# Should show:
# - peeks-general-purpose
# - peeks-system
# - gpu (existing)
# - general-purpose (EKS Auto Mode default)
# - system (EKS Auto Mode default)
```

### Step 3: Update Workloads to Use Custom NodePools

#### Option A: Update Existing Deployments

For Ray services, update the Kro RGD to use custom nodepools:

```yaml
# In ray-service.yaml
spec:
  nodeSelector:
    karpenter.sh/nodepool: peeks-general-purpose  # Changed from general-purpose
```

For system components:
```yaml
spec:
  nodeSelector:
    karpenter.sh/nodepool: peeks-system  # Changed from system
```

#### Option B: Gradual Migration

1. **New workloads**: Use `peeks-*` nodepools
2. **Existing workloads**: Keep on default nodepools
3. **Migrate gradually**: Update and restart pods one by one

### Step 4: Cordon Default NodePools (Optional)

To prevent new pods from scheduling on default nodepools:

```bash
# Cordon all nodes in default general-purpose nodepool
kubectl get nodes -l karpenter.sh/nodepool=general-purpose -o name | \
  xargs -I {} kubectl cordon {}

# Cordon all nodes in default system nodepool
kubectl get nodes -l karpenter.sh/nodepool=system -o name | \
  xargs -I {} kubectl cordon {}
```

### Step 5: Drain and Delete Default NodePool Nodes

**WARNING**: This will cause pod disruptions. Do this during maintenance window.

```bash
# Drain general-purpose nodes
kubectl get nodes -l karpenter.sh/nodepool=general-purpose -o name | \
  xargs -I {} kubectl drain {} --ignore-daemonsets --delete-emptydir-data

# Drain system nodes
kubectl get nodes -l karpenter.sh/nodepool=system -o name | \
  xargs -I {} kubectl drain {} --ignore-daemonsets --delete-emptydir-data
```

Pods will be rescheduled on the custom nodepools.

### Step 6: Delete Default NodePools (Optional)

**WARNING**: Only do this if you're sure all workloads are migrated.

```bash
# Delete default nodepools
kubectl delete nodepool general-purpose
kubectl delete nodepool system
```

## Rollback Plan

If issues occur, disable custom nodepools:

```bash
# 1. Set customNodepools.enabled: false
vim gitops/addons/bootstrap/default/addons/platform-manifests/values.yaml

# 2. Commit and sync
git add gitops/addons/bootstrap/default/addons/platform-manifests/values.yaml
git commit -m "Disable custom nodepools - rollback"
git push

kubectl patch application platform-manifests-peeks-hub -n argocd --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'

# 3. Delete custom nodepools
kubectl delete nodepool peeks-general-purpose peeks-system

# 4. Uncordon default nodes if cordoned
kubectl get nodes -o name | xargs -I {} kubectl uncordon {}
```

## Monitoring

### Check NodePool Status
```bash
kubectl get nodepools
kubectl describe nodepool peeks-general-purpose
kubectl describe nodepool peeks-system
```

### Check Node Distribution
```bash
# Nodes per nodepool
kubectl get nodes -L karpenter.sh/nodepool

# Pods per nodepool
kubectl get pods -A -o wide | awk '{print $8}' | sort | uniq -c
```

### Check Consolidation Events
```bash
# Watch for disruption events
kubectl get events -A --sort-by='.lastTimestamp' | grep -i "disrupt\|consolidat"
```

## Best Practices

1. **Test in non-production first**: Enable custom nodepools in dev/staging before production
2. **Monitor costs**: Custom nodepools may have different cost profiles
3. **Gradual migration**: Don't rush - migrate workloads incrementally
4. **Keep GPU nodepool**: The default GPU nodepool settings are already good
5. **Document changes**: Update runbooks with new nodepool names

## Troubleshooting

### Pods Not Scheduling on Custom NodePools

Check if nodeSelector is correct:
```bash
kubectl get pod <pod-name> -o yaml | grep -A 5 nodeSelector
```

Should show:
```yaml
nodeSelector:
  karpenter.sh/nodepool: peeks-general-purpose
```

### Nodes Not Being Created

Check NodePool status:
```bash
kubectl describe nodepool peeks-general-purpose
```

Look for errors in conditions.

### Too Many Nodes

If both default and custom nodepools are active, you may have duplicate capacity:
```bash
kubectl get nodes -L karpenter.sh/nodepool
```

Consider cordoning or deleting default nodepool nodes.

## Cost Implications

Custom nodepools with longer consolidation times may result in:
- **Slightly higher costs**: Nodes stay around longer
- **Better stability**: Fewer pod disruptions
- **Faster scaling**: Nodes available for quick pod placement

For workshop environments, the stability benefit outweighs the minimal cost increase.

## Summary

Custom PEEKS nodepools provide:
- ✅ Less aggressive consolidation (10m vs 30s)
- ✅ Better stability for long-running workloads
- ✅ Easier identification (managed-by: peeks label)
- ✅ Configurable via GitOps
- ✅ Gradual migration path
- ✅ Easy rollback

The default EKS Auto Mode nodepools remain available as fallback.
