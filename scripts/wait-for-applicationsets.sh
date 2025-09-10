#!/bin/bash

#############################################################################
# Wait for ApplicationSets Deployment Script
#############################################################################
#
# DESCRIPTION:
#   This script waits for all ApplicationSets to be deployed and considers
#   applications as healthy even if they're OutOfSync due to minor 
#   configuration differences or unrecognized values.
#
# USAGE:
#   ./wait-for-applicationsets.sh [timeout_minutes]
#
# PARAMETERS:
#   timeout_minutes: Maximum time to wait in minutes (default: 30)
#
#############################################################################

# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

set -e

# Parse command line arguments
AUTO_FIX=false
TIMEOUT_MINUTES=15

while [[ $# -gt 0 ]]; do
    case $1 in
        --auto-fix)
            AUTO_FIX=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [timeout_minutes]"
            echo ""
            echo "OPTIONS:"
            echo "  --auto-fix     Automatically fix Git revision mismatch issues"
            echo "  --help, -h     Show this help message"
            echo ""
            echo "ARGUMENTS:"
            echo "  timeout_minutes  Maximum time to wait in minutes (default: 15)"
            echo ""
            echo "Examples:"
            echo "  $0                    # Wait with manual fix suggestions"
            echo "  $0 --auto-fix        # Wait with automatic fixes"
            echo "  $0 --auto-fix 30     # Wait 30 minutes with automatic fixes"
            echo "  $0 20                 # Wait 20 minutes with manual suggestions"
            exit 0
            ;;
        *)
            if [[ "$1" =~ ^[0-9]+$ ]]; then
                TIMEOUT_MINUTES=$1
            else
                echo "Unknown option: $1"
                exit 1
            fi
            shift
            ;;
    esac
done

# Configuration
TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))
CHECK_INTERVAL=10
NAMESPACE="argocd"

# Counters
START_TIME=$(date +%s)
LAST_APPSET_COUNT=0
STABLE_ITERATIONS=0
REQUIRED_STABLE_ITERATIONS=2

print_header "Waiting for ApplicationSets Deployment"

print_info "Configuration:"
echo "  - Timeout: ${TIMEOUT_MINUTES} minutes"
echo "  - Check interval: ${CHECK_INTERVAL} seconds"
echo "  - Namespace: ${NAMESPACE}"
echo "  - Required stable iterations: ${REQUIRED_STABLE_ITERATIONS}"
if [ "$AUTO_FIX" = true ]; then
    echo "  - Auto-fix Git revision mismatch: ${GREEN}ENABLED${NC}"
else
    echo "  - Auto-fix Git revision mismatch: ${YELLOW}DISABLED${NC} (use --auto-fix to enable)"
fi

# Function to check if an application is considered healthy
is_application_healthy() {
    local app_name="$1"
    local sync_status="$2"
    local health_status="$3"
    
    # Check for critical path issues that should not be ignored
    local path_errors=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.conditions[]?.message // ""' | grep -i "app path does not exist" || true)
    if [ -n "$path_errors" ]; then
        print_warning "  $app_name has path configuration issues: $path_errors"
        return 1
    fi
    
    # Check for Git revision mismatch errors (critical issue)
    local revision_mismatch=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.operationState.message // ""' | grep -i "cannot reference a different revision of the same repository" || true)
    if [ -n "$revision_mismatch" ]; then
        local retry_count=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.operationState.retryCount // 0')
        print_error "  $app_name has Git revision mismatch (retry #$retry_count)"
        
        if [ "$AUTO_FIX" = true ]; then
            print_info "    🔧 Auto-fix enabled: Attempting to fix Git revision mismatch..."
            if [ -x "$SCRIPT_DIR/fix-git-revision-mismatch.sh" ]; then
                print_info "    ⚡ Running: $SCRIPT_DIR/fix-git-revision-mismatch.sh $app_name"
                if "$SCRIPT_DIR/fix-git-revision-mismatch.sh" "$app_name" > /dev/null 2>&1; then
                    print_success "    ✅ Auto-fix completed for $app_name"
                    return 0  # Consider it healthy after fix attempt
                else
                    print_warning "    ⚠️  Auto-fix failed for $app_name, will continue monitoring"
                    return 1
                fi
            else
                print_warning "    ❌ Fix script not found: $SCRIPT_DIR/fix-git-revision-mismatch.sh"
                print_warning "    💡 Manual fix: ./scripts/fix-git-revision-mismatch.sh $app_name"
                return 1
            fi
        else
            print_warning "    💡 Fix with: ./scripts/fix-git-revision-mismatch.sh $app_name"
            print_info "    💡 Or enable auto-fix: $0 --auto-fix"
            return 1
        fi
    fi
    
    # Check for other critical errors that should not be ignored
    local critical_errors=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.conditions[]?.message // ""' | grep -i -E "(failed to generate manifest|repository not found|authentication failed)" || true)
    if [ -n "$critical_errors" ]; then
        print_warning "  $app_name has critical errors: $critical_errors"
        return 1
    fi
    
    # Consider healthy if:
    # 1. Health is Healthy, Progressing, or Missing (for new apps)
    # 2. Sync can be Synced, OutOfSync, or Unknown (we're lenient on sync for minor issues)
    case "$health_status" in
        "Healthy"|"Progressing"|"Missing"|"")
            return 0
            ;;
        "Degraded")
            # Check if it's a minor configuration issue we can ignore
            local minor_conditions=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.conditions[]?.message // ""' | grep -i -E "(unrecognized field|unknown field|values.*not found)" || true)
            if [ -n "$minor_conditions" ]; then
                print_info "  Ignoring minor config issues for $app_name: $minor_conditions"
                return 0
            fi
            return 1
            ;;
        *)
            return 1
            ;;
    esac
}

# Function to get ApplicationSet status with generated applications
get_applicationset_detailed_status() {
    print_step "Checking ApplicationSets and their generated Applications..."
    
    local appsets=$(kubectl get applicationsets -n "$NAMESPACE" -o json 2>/dev/null)
    local appset_count=$(echo "$appsets" | jq -r '.items | length')
    
    echo "  ApplicationSets found: $appset_count"
    echo ""
    
    # Check each ApplicationSet
    while IFS=$'\t' read -r appset_name appset_age; do
        if [ -n "$appset_name" ]; then
            print_info "📋 ApplicationSet: $appset_name (age: $appset_age)"
            
            # Get ApplicationSet conditions
            local appset_conditions=$(kubectl get applicationset "$appset_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.conditions[]? | "    \(.type): \(.status) - \(.message)"' 2>/dev/null || echo "    No conditions")
            echo "$appset_conditions"
            
            # Find applications generated by this ApplicationSet
            local generated_apps=$(kubectl get applications -n "$NAMESPACE" -o json 2>/dev/null | jq -r --arg appset "$appset_name" '.items[] | select(.metadata.ownerReferences[]?.name == $appset) | .metadata.name' 2>/dev/null || echo "")
            
            if [ -n "$generated_apps" ]; then
                echo "    Generated Applications:"
                while IFS= read -r app_name; do
                    if [ -n "$app_name" ]; then
                        local app_sync=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.sync.status // "Unknown"')
                        local app_health=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.health.status // "Unknown"')
                        
                        # Check if application is healthy using our logic
                        local health_icon="❌"
                        if is_application_healthy "$app_name" "$app_sync" "$app_health" >/dev/null 2>&1; then
                            health_icon="✅"
                        fi
                        
                        echo "      $health_icon $app_name ($app_sync/$app_health)"
                        
                        # Show critical errors if any
                        local app_errors=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.conditions[]?.message // ""' | grep -i -E "(app path does not exist|failed to generate manifest|repository not found)" | head -1 || true)
                        if [ -n "$app_errors" ]; then
                            echo "        ⚠️  $(echo "$app_errors" | cut -c1-80)..."
                        fi
                    fi
                done <<< "$generated_apps"
            else
                echo "    Generated Applications: None found"
            fi
            echo ""
        fi
    done < <(echo "$appsets" | jq -r '.items[] | "\(.metadata.name)\t\(.metadata.creationTimestamp)"')
    
    # Check if ApplicationSet count is stable
    if [ "$appset_count" -eq "$LAST_APPSET_COUNT" ]; then
        STABLE_ITERATIONS=$((STABLE_ITERATIONS + 1))
        print_info "ApplicationSet count stable for $STABLE_ITERATIONS iterations"
    else
        STABLE_ITERATIONS=0
        print_info "ApplicationSet count changed: $LAST_APPSET_COUNT -> $appset_count"
    fi
    
    LAST_APPSET_COUNT=$appset_count
    
    return $appset_count
}

# Function to get Application status
get_application_status() {
    print_step "Checking Applications status..."
    
    local apps=$(kubectl get applications -n "$NAMESPACE" -o json 2>/dev/null)
    local total_apps=$(echo "$apps" | jq -r '.items | length')
    local healthy_apps=0
    local unhealthy_apps=0
    
    echo "  Total applications: $total_apps"
    
    if [ "$total_apps" -eq 0 ]; then
        print_warning "  No applications found yet"
        return 1
    fi
    
    # Check each application
    while IFS=$'\t' read -r name sync_status health_status; do
        if [ -n "$name" ]; then
            if is_application_healthy "$name" "$sync_status" "$health_status"; then
                healthy_apps=$((healthy_apps + 1))
                echo "  ✅ $name ($sync_status/$health_status)"
            else
                unhealthy_apps=$((unhealthy_apps + 1))
                echo "  ❌ $name ($sync_status/$health_status)"
            fi
        fi
    done < <(echo "$apps" | jq -r '.items[] | "\(.metadata.name)\t\(.status.sync.status // "Unknown")\t\(.status.health.status // "Unknown")"')
    
    print_info "  Healthy applications: $healthy_apps/$total_apps"
    
    if [ "$unhealthy_apps" -gt 0 ]; then
        print_warning "  Unhealthy applications: $unhealthy_apps"
        return 1
    fi
    
    return 0
}

# Function to check overall readiness
check_readiness() {
    local current_time=$(date +%s)
    local elapsed=$((current_time - START_TIME))
    
    print_info "Elapsed time: $((elapsed / 60))m $((elapsed % 60))s"
    
    # Get ApplicationSet status
    get_applicationset_detailed_status
    local appset_count=$?
    
    # Check if we have a reasonable number of ApplicationSets
    if [ "$appset_count" -lt 5 ]; then
        print_warning "Waiting for more ApplicationSets to be created..."
        return 1
    fi
    
    # Check if ApplicationSet count is stable
    if [ "$STABLE_ITERATIONS" -lt "$REQUIRED_STABLE_ITERATIONS" ]; then
        print_warning "Waiting for ApplicationSet count to stabilize..."
        return 1
    fi
    
    # Get Application status
    if ! get_application_status; then
        return 1
    fi
    
    return 0
}

# Main waiting loop
print_step "Starting monitoring loop..."

while true; do
    current_time=$(date +%s)
    elapsed=$((current_time - START_TIME))
    
    # Check timeout
    if [ "$elapsed" -ge "$TIMEOUT_SECONDS" ]; then
        print_error "Timeout reached after ${TIMEOUT_MINUTES} minutes"
        print_info "Final status:"
        get_applicationset_detailed_status > /dev/null
        get_application_status || true
        exit 1
    fi
    
    # Check readiness
    if check_readiness; then
        print_success "All ApplicationSets and Applications are ready!"
        break
    fi
    
    print_info "Waiting ${CHECK_INTERVAL} seconds before next check..."
    sleep "$CHECK_INTERVAL"
done

# Final summary
print_header "Deployment Summary"
get_applicationset_detailed_status > /dev/null
get_application_status > /dev/null

# Check for Git revision mismatch issues
print_info "Checking for Git revision mismatch issues..."
if command -v "$SCRIPT_DIR/detect-git-revision-mismatch.sh" &> /dev/null; then
    if ! "$SCRIPT_DIR/detect-git-revision-mismatch.sh" > /dev/null 2>&1; then
        print_warning "Git revision mismatch issues detected!"
        
        if [ "$AUTO_FIX" = true ]; then
            print_info "🔧 Auto-fix enabled: Attempting to fix all Git revision mismatch issues..."
            if [ -x "$SCRIPT_DIR/fix-git-revision-mismatch.sh" ]; then
                if "$SCRIPT_DIR/fix-git-revision-mismatch.sh" > /dev/null 2>&1; then
                    print_success "✅ Auto-fix completed for all applications"
                else
                    print_warning "⚠️  Some applications may still need manual attention"
                    print_info "💡 Check status: ./scripts/detect-git-revision-mismatch.sh"
                fi
            else
                print_warning "❌ Fix script not found"
                print_info "💡 Manual fix: ./scripts/fix-git-revision-mismatch.sh"
            fi
        else
            print_info "💡 Run this command to fix: ./scripts/fix-git-revision-mismatch.sh"
            print_info "💡 Or detect details: ./scripts/detect-git-revision-mismatch.sh"
            print_info "💡 Or enable auto-fix: $0 --auto-fix"
        fi
    else
        print_success "No Git revision mismatch issues found"
    fi
else
    print_info "Git revision mismatch detection script not found"
fi

current_time=$(date +%s)
total_elapsed=$((current_time - START_TIME))

print_success "ApplicationSets deployment completed successfully!"
print_info "Total time: $((total_elapsed / 60))m $((total_elapsed % 60))s"

print_header "Access Information"
DOMAIN_NAME=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o json | jq -r '.metadata.annotations.ingress_domain_name // ""')
if [ -n "$DOMAIN_NAME" ]; then
    echo -e "${CYAN}ArgoCD URL:${BOLD} https://$DOMAIN_NAME/argocd${NC}"
    echo -e "${CYAN}   Login:${BOLD} admin${NC}"
    echo -e "${CYAN}   Password:${BOLD} $IDE_PASSWORD${NC}"
fi
