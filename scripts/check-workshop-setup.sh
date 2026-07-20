#!/bin/bash
set -e

# Workshop setup validation script
# This script checks if all critical workshop components are healthy
# Non-critical components may still be syncing without blocking the workshop

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/colors.sh"

# Define critical applications that MUST be healthy for workshop to function
CRITICAL_APPS=(
    "cert-manager-${RESOURCE_PREFIX}-hub"
    "external-secrets-${RESOURCE_PREFIX}-hub"
    "ingress-nginx-${RESOURCE_PREFIX}-hub"
    "metrics-server-${RESOURCE_PREFIX}-hub"
    "keycloak-${RESOURCE_PREFIX}-hub"
    "backstage-${RESOURCE_PREFIX}-hub"
    "gitlab-${RESOURCE_PREFIX}-hub"
    "argo-workflows-${RESOURCE_PREFIX}-hub"
)

# Apps that are OK if Healthy but OutOfSync (known ArgoCD ignore issues)
HEALTHY_OUTOFSYNC_OK_APPS=(
    "keycloak-${RESOURCE_PREFIX}-hub"
    "backstage-${RESOURCE_PREFIX}-hub"
)

print_header "Workshop Setup Validation"

# Track overall status
OVERALL_STATUS=0

# Check 1: ArgoCD Applications - only critical ones
print_step "Checking ArgoCD applications..."

# Check critical apps
critical_unhealthy=0
for app in "${CRITICAL_APPS[@]}"; do
    app_info=$(kubectl get application "$app" -n argocd -o json 2>/dev/null | \
        jq -r '{sync: .status.sync.status, health: .status.health.status, operation: (.status.operationState.phase // "None")}' 2>/dev/null || echo '{"sync":"Unknown","health":"Unknown","operation":"None"}')
    
    sync_status=$(echo "$app_info" | jq -r '.sync')
    health_status=$(echo "$app_info" | jq -r '.health')
    operation_status=$(echo "$app_info" | jq -r '.operation')
    
    # Check if app is in HEALTHY_OUTOFSYNC_OK_APPS
    is_healthy_outofsync_ok=false
    for healthy_outofsync_app in "${HEALTHY_OUTOFSYNC_OK_APPS[@]}"; do
        if [[ "$app" == "$healthy_outofsync_app" ]]; then
            is_healthy_outofsync_ok=true
            break
        fi
    done
    
    # Determine if app is OK
    if [[ "$health_status" == "Healthy" ]] && [[ "$sync_status" == "Synced" ]]; then
        print_success "  $app: Healthy/Synced"
    elif [[ "$is_healthy_outofsync_ok" == true ]] && [[ "$health_status" == "Healthy" ]] && [[ "$operation_status" == "Succeeded" ]]; then
        print_success "  $app: Healthy/OutOfSync (operation Succeeded - OK)"
    else
        print_error "  $app: $health_status/$sync_status (operation: $operation_status)"
        critical_unhealthy=$((critical_unhealthy + 1))
    fi
done

if [ $critical_unhealthy -eq 0 ]; then
    print_success "ArgoCD check completed"
else
    print_error "ArgoCD check failed - $critical_unhealthy critical apps unhealthy"
    OVERALL_STATUS=1
fi

echo ""

# Check 2: Ray+vLLM CodeBuild
print_step "Checking Ray+vLLM image build..."
if "$SCRIPT_DIR/check-ray-build.sh"; then
    print_success "Ray build check completed"
else
    print_error "Ray build check failed"
    OVERALL_STATUS=1
fi

echo ""

# Final summary
print_header "Validation Summary"
if [ $OVERALL_STATUS -eq 0 ]; then
    print_success "All workshop components are healthy!"
else
    print_warning "Some components need attention. Review the output above."
fi

exit $OVERALL_STATUS
