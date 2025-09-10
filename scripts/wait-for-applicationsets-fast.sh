#!/bin/bash

#############################################################################
# Fast Wait for ApplicationSets Deployment Script
#############################################################################
#
# DESCRIPTION:
#   Optimized version that waits for ApplicationSets with minimal overhead
#
# USAGE:
#   ./wait-for-applicationsets-fast.sh [timeout_minutes]
#
#############################################################################

# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

set -e

# Parse command line arguments
AUTO_FIX=false
TIMEOUT_MINUTES=10

while [[ $# -gt 0 ]]; do
    case $1 in
        --auto-fix)
            AUTO_FIX=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [timeout_minutes]"
            echo ""
            echo "Fast version of ApplicationSets monitoring with Git revision mismatch support"
            echo ""
            echo "OPTIONS:"
            echo "  --auto-fix     Automatically fix Git revision mismatch issues"
            echo "  --help, -h     Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Fast wait with manual fix suggestions"
            echo "  $0 --auto-fix        # Fast wait with automatic fixes"
            echo "  $0 --auto-fix 20     # Fast wait 20 minutes with automatic fixes"
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

# Configuration - Optimized for speed
TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))
CHECK_INTERVAL=5
NAMESPACE="argocd"
MIN_APPSETS=5
REQUIRED_STABLE_ITERATIONS=1

# Counters
START_TIME=$(date +%s)
LAST_APPSET_COUNT=0
STABLE_ITERATIONS=0

print_header "Fast ApplicationSets Deployment Check"
print_info "Timeout: ${TIMEOUT_MINUTES}m | Interval: ${CHECK_INTERVAL}s | Min AppSets: ${MIN_APPSETS}"

# Fast health check - only check critical conditions
is_app_ready() {
    local app_name="$1"
    
    # Get app status in one call
    local app_data=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null)
    
    # Check for Git revision mismatch (critical issue)
    local revision_mismatch=$(echo "$app_data" | jq -r '.status.operationState.message // ""' | grep -i "cannot reference a different revision of the same repository" || true)
    if [ -n "$revision_mismatch" ]; then
        if [ "$AUTO_FIX" = true ] && [ -x "$SCRIPT_DIR/fix-git-revision-mismatch.sh" ]; then
            # Attempt auto-fix in background for speed
            "$SCRIPT_DIR/fix-git-revision-mismatch.sh" "$app_name" > /dev/null 2>&1 &
            return 0  # Consider healthy after fix attempt
        else
            return 1
        fi
    fi
    
    # Check for critical errors
    local critical_errors=$(echo "$app_data" | jq -r '.status.conditions[]?.message // ""' | grep -i -E "(app path does not exist|failed to generate|repository not found|authentication failed)" || true)
    if [ -n "$critical_errors" ]; then
        return 1
    fi
    
    # Check health status
    local health=$(echo "$app_data" | jq -r '.status.health.status // "Unknown"')
    case "$health" in
        "Healthy"|"Progressing"|"Missing"|"") return 0 ;;
        *) return 1 ;;
    esac
}

# Fast status check
check_fast_status() {
    local current_time=$(date +%s)
    local elapsed=$((current_time - START_TIME))
    
    # Get counts efficiently
    local appset_count=$(kubectl get applicationsets -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
    local total_apps=$(kubectl get applications -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
    
    printf "\r⏱️  %02dm:%02ds | AppSets: %d | Apps: %d" $((elapsed/60)) $((elapsed%60)) "$appset_count" "$total_apps"
    
    # Check minimum ApplicationSets
    if [ "$appset_count" -lt "$MIN_APPSETS" ]; then
        return 1
    fi
    
    # Check stability
    if [ "$appset_count" -eq "$LAST_APPSET_COUNT" ]; then
        STABLE_ITERATIONS=$((STABLE_ITERATIONS + 1))
    else
        STABLE_ITERATIONS=0
    fi
    LAST_APPSET_COUNT=$appset_count
    
    if [ "$STABLE_ITERATIONS" -lt "$REQUIRED_STABLE_ITERATIONS" ]; then
        return 1
    fi
    
    # Quick app health check - only if we have apps
    if [ "$total_apps" -eq 0 ]; then
        return 1
    fi
    
    # Check a sample of apps for critical issues (not all for speed)
    local unhealthy=0
    local checked=0
    while IFS= read -r app_name && [ "$checked" -lt 10 ]; do
        if [ -n "$app_name" ]; then
            if ! is_app_ready "$app_name"; then
                unhealthy=$((unhealthy + 1))
            fi
            checked=$((checked + 1))
        fi
    done < <(kubectl get applications -n "$NAMESPACE" -o name 2>/dev/null | sed 's|application.argoproj.io/||' | head -10)
    
    # Allow some unhealthy apps for speed
    if [ "$unhealthy" -gt 3 ]; then
        return 1
    fi
    
    return 0
}

# Main loop
echo ""
while true; do
    current_time=$(date +%s)
    elapsed=$((current_time - START_TIME))
    
    # Check timeout
    if [ "$elapsed" -ge "$TIMEOUT_SECONDS" ]; then
        echo ""
        print_error "Timeout reached after ${TIMEOUT_MINUTES} minutes"
        exit 1
    fi
    
    # Check readiness
    if check_fast_status; then
        echo ""
        print_success "ApplicationSets appear ready! (Fast check completed)"
        break
    fi
    
    sleep "$CHECK_INTERVAL"
done

# Quick final summary
echo ""
print_header "Fast Check Summary"
appset_count=$(kubectl get applicationsets -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
app_count=$(kubectl get applications -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
total_elapsed=$(($(date +%s) - START_TIME))

print_info "ApplicationSets: $appset_count | Applications: $app_count"
print_info "Total time: $((total_elapsed / 60))m $((total_elapsed % 60))s"

# Quick check for Git revision mismatch
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ -x "$SCRIPT_DIR/detect-git-revision-mismatch.sh" ]; then
    if ! "$SCRIPT_DIR/detect-git-revision-mismatch.sh" > /dev/null 2>&1; then
        if [ "$AUTO_FIX" = true ]; then
            print_info "🔧 Auto-fix: Attempting to fix Git revision mismatch issues..."
            "$SCRIPT_DIR/fix-git-revision-mismatch.sh" > /dev/null 2>&1 && print_success "✅ Auto-fix completed" || print_warning "⚠️  Auto-fix may need more time"
        else
            print_warning "⚠️  Git revision mismatch detected! Run: ./scripts/fix-git-revision-mismatch.sh"
            print_info "💡 Or use: $0 --auto-fix for automatic fixes"
        fi
    fi
fi

# Show access info
DOMAIN_NAME=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o json 2>/dev/null | jq -r '.metadata.annotations.ingress_domain_name // ""')
if [ -n "$DOMAIN_NAME" ]; then
    echo ""
    print_header "Access Information"
    echo -e "${CYAN}ArgoCD URL:${BOLD} https://$DOMAIN_NAME/argocd${NC}"
    echo -e "${CYAN}   Login:${BOLD} admin${NC}"
    echo -e "${CYAN}   Password:${BOLD} $IDE_PASSWORD${NC}"
fi
