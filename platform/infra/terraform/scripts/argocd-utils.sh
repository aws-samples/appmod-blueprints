#!/bin/bash

# Robust ArgoCD utility functions
# Source this file in other scripts: source "$(dirname "$0")/argocd-utils.sh"

export CORE_APPS=(
    "external-secrets"
    "ingress-nginx"
    "argocd"
)

export BOOTSTRAP_APPS=(
    "bootstrap"
    "cluster-addons"
    "clusters"
    "fleet-secrets"
)

# Function to terminate ArgoCD application operations
terminate_argocd_operation() {
    local app_name=$1
    
    kubectl patch application.argoproj.io "$app_name" -n argocd --type='merge' -p='{"operation":null}' 2>/dev/null || true
}

# Function to refresh ArgoCD application
refresh_argocd_app() {
    local app_name=$1
    local hard_refresh=${2:-true}
    
    local refresh_type="normal"
    [ "$hard_refresh" = "true" ] && refresh_type="hard"
    
    kubectl annotate application.argoproj.io "$app_name" -n argocd argocd.argoproj.io/refresh="$refresh_type" --overwrite 2>/dev/null || true
}

# Function to sync ArgoCD application
sync_argocd_app() {
    local app_name=$1
    
    kubectl patch application.argoproj.io "$app_name" -n argocd --type='merge' -p='{"operation":{"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
}

# Handle stuck operations (terminate if running > 5 mins)
handle_stuck_operations() {
    local stuck_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.items[] | select(.status.operationState?.phase == "Running" and (.status.operationState.startedAt | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 300)) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$stuck_apps" ]; then
        echo "$stuck_apps" | while read -r app; do
            [ -n "$app" ] && terminate_argocd_operation "$app" && refresh_argocd_app "$app"
        done
    fi
}

# Handle revision conflicts
handle_revision_conflicts() {
    local error_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type == "ComparisonError" and (.message | contains("cannot reference a different revision")))) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$error_apps" ]; then
        echo "$error_apps" | while read -r app; do
            [ -n "$app" ] && terminate_argocd_operation "$app" && refresh_argocd_app "$app"
        done
    fi
}

# Wait for ArgoCD applications health (30min timeout)
wait_for_argocd_apps_health() {
    local timeout=${1:-1800}  # 30 minutes
    local start_time=$(date +%s)
    local end_time=$((start_time + timeout))
    
    while [ $(date +%s) -lt $end_time ]; do
        if ! kubectl get applications -n argocd >/dev/null 2>&1; then
            sleep 30
            continue
        fi
        
        local app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{"\n"}{end}' 2>/dev/null)
        local total_apps=$(echo "$app_status" | grep -v '^$' | wc -l)
        
        if [ "$total_apps" -eq 0 ]; then
            sleep 30
            continue
        fi
        
        local healthy_apps=$(echo "$app_status" | awk '$2 == "Healthy" {count++} END {print count+0}')
        local health_pct=$((healthy_apps * 100 / total_apps))
        
        log "ArgoCD status: $healthy_apps/$total_apps healthy ($health_pct%)"
        
        if [ $health_pct -ge 80 ]; then
            log "ArgoCD applications sufficiently healthy ($health_pct%)"
            return 0
        fi
        
        handle_stuck_operations
        handle_revision_conflicts
        sleep 30
    done
    
    log "Timeout waiting for ArgoCD applications health"
    return 1
}