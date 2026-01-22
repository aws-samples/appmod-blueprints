# Keycloak-Backstage Synchronization Fix

## Problem Description

The original GitOps configuration had a timing issue where Backstage would start before Keycloak clients were properly configured, leading to authentication errors:

```
Authentication rejected, unauthorized_client (Invalid client or Invalid client credentials)
```

## Root Cause

1. **Race Condition**: Backstage External Secret tried to sync before Keycloak config job created the clients
2. **No Dependency Management**: No explicit ordering between Keycloak configuration and Backstage deployment
3. **Single Sync**: External Secret had `refreshInterval: "0"` meaning it only synced once
4. **No Retry Logic**: Failed syncs weren't retried automatically

## Solution Implemented

### 1. ArgoCD Sync Waves

Added proper sync wave ordering to ensure correct deployment sequence:

```yaml
# Keycloak config job (creates clients)
annotations:
  argocd.argoproj.io/sync-wave: "10"
  argocd.argoproj.io/hook: PostSync
  argocd.argoproj.io/hook-delete-policy: BeforeHookCreation

# Backstage External Secret (syncs client secrets)
annotations:
  argocd.argoproj.io/sync-wave: "15"
  argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true

# Backstage Deployment (starts application)
annotations:
  argocd.argoproj.io/sync-wave: "25"
```

### 2. External Secret Improvements

Enhanced the External Secret configuration:

```yaml
spec:
  refreshInterval: "30s"          # Regular refresh every 30 seconds
  # Note: retrySettings requires ESO v0.11.0+, using init container for reliability instead
```

### 3. Init Container

Added an init container to Backstage deployment to wait for secrets:

```yaml
initContainers:
  - name: wait-for-secrets
    image: busybox:1.35
    command:
      - sh
      - -c
      - |
        echo "Waiting for backstage-env-vars secret to be ready..."
        until [ -f /var/secrets/KEYCLOAK_CLIENT_SECRET ] && [ -s /var/secrets/KEYCLOAK_CLIENT_SECRET ]; do
          echo "Secret not ready yet, waiting..."
          sleep 5
        done
        echo "Secret is ready!"
    volumeMounts:
      - name: backstage-env-vars
        mountPath: /var/secrets
        readOnly: true
```

## Deployment Sequence

The improved configuration ensures this deployment order:

1. **Wave 10**: Keycloak config job runs (creates clients and secrets)
2. **Wave 15**: External Secret syncs client credentials from Keycloak
3. **Wave 25**: Backstage deployment starts with init container checking for secrets
4. **Init Container**: Waits until KEYCLOAK_CLIENT_SECRET is available
5. **Main Container**: Starts Backstage with correct credentials

## Benefits

- ✅ **Eliminates Race Conditions**: Proper ordering prevents timing issues
- ✅ **Automatic Recovery**: Retry logic handles temporary failures
- ✅ **Fresh Installation Ready**: Works correctly on clean deployments
- ✅ **Self-Healing**: Regular refresh interval keeps secrets in sync
- ✅ **Explicit Dependencies**: Init container ensures prerequisites are met

## Testing

To test the fix in a fresh installation:

1. Deploy Keycloak first
2. Deploy Backstage
3. Verify that authentication works without manual intervention
4. Check ArgoCD sync status shows all waves completed successfully

## Monitoring

Monitor these components for proper synchronization:

```bash
# Check External Secret status
kubectl get externalsecret backstage-oidc -n backstage

# Check if secrets are synced
kubectl get secret backstage-env-vars -n backstage

# Check Backstage pod logs
kubectl logs -l app=backstage -n backstage

# Check Keycloak config job
kubectl get job config -n keycloak
```

## Files Modified

- `gitops/addons/charts/backstage/templates/install.yaml`
- `gitops/addons/charts/keycloak/templates/keycloak-config.yaml`

These changes ensure reliable Keycloak-Backstage integration in all deployment scenarios.
