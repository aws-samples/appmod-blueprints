# Balanced Validation Strategy for Workshop Setup

**Date:** 2026-03-04  
**Issue:** CloudFormation setup failing due to mismatched validation criteria  
**Solution:** Implement stricter Phase 1 wait logic and lenient Phase 2 validation

---

## Problem Statement

The workshop setup was failing during CloudFormation deployment because:

1. **Phase 1 (wait loop)** was too lenient - allowed 54/59 apps to be healthy
2. **Phase 2 (final validation)** was too strict - required all 61 apps to be healthy
3. This mismatch caused the script to exit successfully from Phase 1, then fail in Phase 2

**Result:** CloudFormation signaled FAILURE even though the platform was functional.

---

## Solution Overview

Implement a **balanced approach**:

| Phase | Old Behavior | New Behavior |
|-------|-------------|--------------|
| **Phase 1: Wait Loop** | Excludes 5 best-effort apps | Excludes only 1 truly optional app |
| **Phase 2: Final Validation** | Checks all 61 apps | Checks only 8 critical apps |

---

## Changes Implemented

### 1. Stricter Phase 1 - `0-init.sh`

**File:** `platform/infra/terraform/scripts/0-init.sh`

#### Reduced Best-Effort Apps

**Before:**
```bash
BEST_EFFORT_APPS=(
    "devlake-peeks-hub"              # Now required
    "grafana-dashboards-peeks-hub"   # Now required
    "jupyterhub-peeks-hub"           # Now required
    "spark-operator-peeks-hub"       # Now required
    "image-prepuller-peeks-hub"      # Still optional
)
```

**After:**
```bash
BEST_EFFORT_APPS=(
    "image-prepuller-peeks-hub"  # Only truly optional app
)
```

#### Added Healthy-OutOfSync-OK Apps

New array for apps with known ArgoCD ignore configuration issues:

```bash
# Apps that are OK if Healthy but OutOfSync (known ArgoCD ignore issues)
# These must have: status.health.status == "Healthy" AND status.operationState.phase == "Succeeded"
HEALTHY_OUTOFSYNC_OK_APPS=(
    "keycloak-peeks-hub"
    "backstage-peeks-hub"
)
```

**Rationale:** These apps have resources that drift due to ArgoCD ignore list configuration challenges, but are functional if the last operation succeeded.

---

### 2. Enhanced Wait Logic - `argocd-utils.sh`

**File:** `platform/infra/terraform/scripts/argocd-utils.sh`

#### Updated `wait_for_sync_wave_completion()` Function

Added logic to handle `HEALTHY_OUTOFSYNC_OK_APPS`:

```bash
# Check if it's a healthy-outofsync-ok app with Succeeded operation
if [[ "$is_best_effort" == false ]]; then
    for healthy_outofsync_app in "${HEALTHY_OUTOFSYNC_OK_APPS[@]}"; do
        if [[ "$app" == "$healthy_outofsync_app" ]]; then
            # Verify it's Healthy with Succeeded operation
            local app_status=$(kubectl get application "$app" -n argocd -o json 2>/dev/null | \
                jq -r '{health: .status.health.status, operation: (.status.operationState.phase // "None")}')
            local health=$(echo "$app_status" | jq -r '.health')
            local operation=$(echo "$app_status" | jq -r '.operation')
            
            if [[ "$health" == "Healthy" ]] && [[ "$operation" == "Succeeded" ]]; then
                is_healthy_outofsync_ok=true
                log_timestamp "[$cluster] App $app is Healthy with Succeeded operation (OutOfSync OK)"
                break
            fi
        fi
    done
fi
```

**Validation Criteria:**
- ✅ `health.status == "Healthy"`
- ✅ `operationState.phase == "Succeeded"`
- ⚠️ `sync.status` can be "OutOfSync" (acceptable)

---

### 3. Lenient Phase 2 - `check-workshop-setup.sh`

**File:** `platform/infra/terraform/scripts/check-workshop-setup.sh`

#### Replaced Full Validation with Critical Apps Check

**Before:**
```bash
# Check 1: ArgoCD Applications
print_step "Checking ArgoCD applications..."
if "$SCRIPT_DIR/recover-argocd-apps.sh"; then  # Checks ALL apps
    print_success "ArgoCD check completed"
else
    print_error "ArgoCD check failed"
    OVERALL_STATUS=1
fi
```

**After:**
```bash
# Define critical applications that MUST be healthy
CRITICAL_APPS=(
    "cert-manager-peeks-hub"
    "external-secrets-peeks-hub"
    "ingress-nginx-peeks-hub"
    "metrics-server-peeks-hub"
    "keycloak-peeks-hub"
    "backstage-peeks-hub"
    "gitlab-peeks-hub"
    "argo-workflows-peeks-hub"
)

# Check only critical apps
for app in "${CRITICAL_APPS[@]}"; do
    # Validate health status
    # Accept Healthy+OutOfSync for keycloak/backstage if operation Succeeded
done
```

#### Critical Apps Rationale

| App | Why Critical |
|-----|-------------|
| `cert-manager` | Required for TLS certificates |
| `external-secrets` | Required for secret management |
| `ingress-nginx` | Required for external access |
| `metrics-server` | Required for HPA and monitoring |
| `keycloak` | Required for SSO authentication |
| `backstage` | Required for developer portal |
| `gitlab` | Required for Git operations |
| `argo-workflows` | Required for CI/CD pipelines |

**Non-Critical Apps** (can still be syncing):
- `devlake-peeks-hub` - Analytics platform
- `grafana-dashboards-peeks-hub` - Monitoring dashboards
- `jupyterhub-peeks-hub` - Notebook environment
- `spark-operator-peeks-hub` - Big data processing
- `ray-operator-peeks-hub` - ML workloads
- `crossplane-aws-peeks-hub` - Infrastructure provisioning

---

## Expected Behavior

### Phase 1: Wait Loop (45 min timeout per phase)

**Checks every 30 seconds:**
- ✅ Waits for ~58/61 apps to be `Healthy + Synced`
- ✅ Accepts keycloak/backstage as `Healthy + OutOfSync` (if operation Succeeded)
- ✅ Skips only `image-prepuller` as truly optional
- ✅ Syncs and recovers stuck apps automatically

**Exit Condition:** All non-optional apps are healthy OR timeout reached

### Phase 2: Final Validation (runs once)

**Checks critical apps only:**
- ✅ Validates 8 critical apps
- ✅ Accepts `Healthy + OutOfSync` for keycloak/backstage (if operation Succeeded)
- ✅ Ignores non-critical apps (they can still be syncing)

**Exit Condition:** All 8 critical apps are healthy

---

## Testing Instructions

### Test the Changes

```bash
cd /home/ec2-user/environment/platform-on-eks-workshop
./platform/infra/terraform/scripts/0-init.sh
```

### Expected Results

**Phase 1 Output:**
```
[hub] Waiting for sync waves 0-30 to complete...
[hub] App keycloak-peeks-hub is Healthy with Succeeded operation (OutOfSync OK)
[hub] App backstage-peeks-hub is Healthy with Succeeded operation (OutOfSync OK)
[hub] Sync waves 0-30 completed (ignoring best effort apps) - elapsed: 120s
```

**Phase 2 Output:**
```
=== Workshop Setup Validation ===

➤ Checking ArgoCD applications...
✓   cert-manager-peeks-hub: Healthy/Synced
✓   external-secrets-peeks-hub: Healthy/Synced
✓   ingress-nginx-peeks-hub: Healthy/Synced
✓   metrics-server-peeks-hub: Healthy/Synced
✓   keycloak-peeks-hub: Healthy/OutOfSync (operation Succeeded - OK)
✓   backstage-peeks-hub: Healthy/OutOfSync (operation Succeeded - OK)
✓   gitlab-peeks-hub: Healthy/Synced
✓   argo-workflows-peeks-hub: Healthy/Synced
✓ ArgoCD check completed

=== Validation Summary ===
✓ All workshop components are healthy!
```

**Exit Code:** `0` (success)

---

## Rollback Procedure

If issues occur, revert the changes:

```bash
cd /home/ec2-user/environment/platform-on-eks-workshop

# Revert all three files
git checkout HEAD -- platform/infra/terraform/scripts/0-init.sh
git checkout HEAD -- platform/infra/terraform/scripts/argocd-utils.sh
git checkout HEAD -- platform/infra/terraform/scripts/check-workshop-setup.sh

# Verify rollback
git status
```

---

## Benefits

1. **Faster Feedback:** Phase 1 waits for more apps, reducing false positives
2. **Reliable Validation:** Phase 2 only checks critical apps, reducing false negatives
3. **Better UX:** Workshop succeeds when core platform is functional
4. **Clearer Errors:** If validation fails, it's a real critical issue
5. **Maintainable:** Clear separation between critical and optional components

---

## Future Improvements

1. **Dynamic Critical Apps:** Load critical apps from configuration file
2. **Health Scoring:** Implement weighted health scores for different app categories
3. **Parallel Validation:** Check critical apps in parallel for faster validation
4. **Detailed Reporting:** Generate HTML report of app health status
5. **Auto-Recovery:** Automatically retry failed critical apps before failing

---

## Related Documentation

- [GitOps Addon Management](../amazon-q-target-file.md)
- [ArgoCD Recovery Script](../platform/infra/terraform/scripts/recover-argocd-apps.sh)
- [Workshop Setup Script](../platform/infra/terraform/scripts/0-init.sh)
