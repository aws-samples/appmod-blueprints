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
