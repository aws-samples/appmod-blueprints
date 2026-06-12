---
inclusion: auto
---

# Troubleshooting Guide

## ArgoCD Issues

### Application Out of Sync
**Symptoms**: Application shows "OutOfSync" status

**Diagnosis**:
```bash
argocd app get <app-name>
argocd app diff <app-name>
```

**Solutions**:
- Check for manual changes in cluster
- Verify Git repository is accessible
- Review sync waves and dependencies
- Check for resource conflicts

### Sync Failures
**Symptoms**: Sync operation fails

**Common Causes**:
- Missing CRDs
- Invalid manifests
- Resource dependencies not met
- Insufficient permissions

**Solutions**:
- Check sync operation logs
- Validate manifests with kubectl dry-run
- Review resource ordering (sync waves)
- Verify service account permissions

## Backstage Issues

### Plugin Not Loading
**Diagnosis**:
```bash
# Check backend logs
kubectl logs -n backstage deployment/backstage-backend

# Check frontend console
# Open browser dev tools
```

**Solutions**:
- Verify plugin registration in backend
- Check plugin dependencies installed
- Review plugin configuration
- Clear browser cache

### Catalog Entities Not Appearing
**Diagnosis**:
```bash
# Check catalog processor logs
kubectl logs -n backstage deployment/backstage-backend | grep catalog
```

**Solutions**:
- Verify catalog provider configuration
- Check entity YAML syntax
- Review entity processor registration
- Refresh catalog manually

## Kro Issues

### RGD Not Discovered
**Diagnosis**:
```bash
kubectl get resourcegraphdefinition -A
kubectl describe rgd <rgd-name> -n kro-system
```

**Solutions**:
- Verify RGD is in correct namespace
- Check Kro controller logs
- Validate RGD YAML syntax
- Ensure Kro CRDs are installed

### ResourceGroup Stuck
**Diagnosis**:
```bash
kubectl describe resourcegroup <name> -n <namespace>
kubectl get events -n <namespace> --sort-by='.lastTimestamp'
```

**Solutions**:
- Check resource dependencies
- Verify required CRDs exist
- Review resource status conditions
- Check for permission issues

## Kubernetes Issues

### Pod CrashLoopBackOff
**Diagnosis**:
```bash
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace> --previous
```

**Common Causes**:
- Application errors
- Missing configuration
- Resource limits too low
- Failed health checks

### ImagePullBackOff
**Diagnosis**:
```bash
kubectl describe pod <pod-name> -n <namespace>
```

**Solutions**:
- Verify image exists in registry
- Check image pull secrets
- Verify registry permissions
- Check network connectivity

## Helm Issues

### Chart Dependency Errors
**Diagnosis**:
```bash
helm dependency list ./gitops/addons/charts/<chart-name>
```

**Solutions**:
```bash
# Build dependencies
task build-helm-dependencies

# Or manually
cd ./gitops/addons/charts/<chart-name>
helm dependency update
```

### Template Rendering Errors
**Diagnosis**:
```bash
helm template <release-name> ./path/to/chart \
  -f values.yaml \
  --debug
```

**Solutions**:
- Check values file syntax
- Verify template syntax
- Review variable references
- Test with minimal values

## Network Issues

### Service Not Accessible
**Diagnosis**:
```bash
kubectl get svc -n <namespace>
kubectl get endpoints -n <namespace>
kubectl describe svc <service-name> -n <namespace>
```

**Solutions**:
- Verify pod labels match service selector
- Check pod readiness
- Review network policies
- Test from within cluster

### Ingress Not Working
**Diagnosis**:
```bash
kubectl get ingress -n <namespace>
kubectl describe ingress <ingress-name> -n <namespace>
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

**Solutions**:
- Verify ingress class
- Check DNS configuration
- Review TLS certificates
- Validate ingress rules

## ACK (AWS Controllers for Kubernetes) Issues

### ACK "scheduled for deletion" loop
**Symptoms**: ACK resource stuck with `InvalidRequestException: You can't create this secret because a secret with this name is already scheduled for deletion`

**Root cause**: AWS Secrets Manager (or other services) has a deletion delay. ACK caches the error and enters a 10h backoff.

**Fix**:
1. Wait for AWS to fully purge the resource (check with `aws secretsmanager describe-secret`)
2. Delete the K8s CR (remove finalizers first if needed)
3. Let KRO/ArgoCD recreate the CR — **new K8s objects don't inherit the cached error**
4. If still stuck, patch `spec.description` or `spec.tags` to bump `.metadata.generation` which forces a fresh reconciliation cycle

### ACK "Resource already exists" after restore
**Symptoms**: ACK tries `CreateSecret` but gets `Resource already exists`

**Fix**: Delete the secret from AWS (`force-delete-without-recovery`), then bump the CR's generation by patching a mutable spec field.

### IAMRoleSelector not taking effect
**Symptoms**: ACK uses the default capability role instead of the cluster-mgmt role

**Fix**: Verify IAMRoleSelector exists with correct `namespaceSelector` and `resourceTypeSelector`. After creating/updating selectors, delete the stuck ACK resource CR to force recreation — ACK picks up selectors only on fresh reconciliation.

### Force ACK reconciliation
The `services.k8s.aws/force-reconcile` annotation does NOT always work (especially with capability-managed ACK). The reliable method is to **patch a mutable spec field** (e.g., `spec.description`, `spec.tags`) to increment `.metadata.generation`.

## ArgoCD 3.x (EKS Capability) Issues

### `dig` function fails on annotations
**Symptoms**: `error calling dig: interface conversion: interface {} is map[string]string, not map[string]interface {}`

**Root cause**: ArgoCD 3.x strict Go template typing. `dig` doesn't work on `map[string]string` (annotations).

**Fix**: Replace `{{ dig "key" default .metadata.annotations }}` with `{{ or (index .metadata.annotations "key") default }}`

### Cluster secret ignored by ArgoCD
**Symptoms**: `controller is configured to ignore cluster`

**Fix**: Add `project: default` to the cluster secret's `stringData`. ArgoCD 3.x requires this field.

### `missingkey=error` with optional annotations
**Symptoms**: `map has no entry for key "annotation_name"`

**Fix**: Use `index` instead of dot notation: `{{ or (index .metadata.annotations "key") "default" }}`

### KRO RGD "breaking changes detected" on CRD update
**Symptoms**: RGD shows `Inactive` with message `cannot update CRD: breaking changes detected: Property X was removed`

**Fix**: Delete the CRD manually (`kubectl delete crd <name>.kro.run`), then sync to let KRO recreate it. **Warning**: This deletes all instances of that CRD — may trigger resource deletion in AWS. Only do this when safe.

## Crossplane Issues

### NAT Gateway reference resolution race condition
**Symptoms**: Route stuck with `referenced field was empty (referenced resource may not yet be ready)` for hours

**Root cause**: `managementPolicies` excludes `LateInitialize` on NATGateway, so the provider never backfills the ID field that `natGatewayIdSelector` needs.

**Fix**: Use composite field patching (`ToCompositeFieldPath` from NATGateway status → `FromCompositeFieldPath` to Route) with `policy.fromFieldPath: Required`.
