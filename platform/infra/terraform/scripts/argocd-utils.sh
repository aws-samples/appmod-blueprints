#!/bin/bash

# Shared ArgoCD utility functions
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

# Function to handle stuck ArgoCD operations
handle_stuck_operations() {
    local timeout_seconds=${1:-600}  # Increased from 180 to 600 seconds (10 minutes)
    
    local stuck_apps=$(kubectl get application.argoproj.io -n argocd -o json 2>/dev/null | \
        jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg timeout "$timeout_seconds" \
        '.items[] | select(.status.operationState?.phase == "Running" and (.status.operationState.startedAt | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - ($timeout | tonumber))) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$stuck_apps" ]; then
        echo "$stuck_apps" | while read -r app; do
            if [ -n "$app" ]; then
                [ -n "$message_prefix" ] && echo "$message_prefix Terminating stuck operation for $app (running > ${timeout_seconds}s)"
                terminate_argocd_operation "$app"
                sleep 2
                refresh_argocd_app "$app"
                sleep 1
                sync_argocd_app "$app"
            fi
        done
        return 0
    fi
    return 1
}

# Function to handle revision conflicts
handle_revision_conflicts() {
    local message_prefix=${1:-""}
    
    local error_apps=$(kubectl get application.argoproj.io -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type == "ComparisonError" and (.message | contains("cannot reference a different revision")))) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$error_apps" ]; then
        echo "$error_apps" | while read -r app; do
            if [ -n "$app" ]; then
                [ -n "$message_prefix" ] && echo "$message_prefix Fixing revision conflict for $app"
                terminate_argocd_operation "$app"
                sleep 2
                refresh_argocd_app "$app" true
                sleep 2
                sync_argocd_app "$app"
            fi
        done
        return 0
    fi
    return 1
}

# Function to wait for ArgoCD applications to be healthy
wait_for_argocd_health() {
    local timeout=${1:-300}
    local check_interval=${2:-30}
    local message_prefix=${3:-""}
    
    local start_time=$(date +%s)
    local end_time=$((start_time + timeout))
    
    while [ $(date +%s) -lt $end_time ]; do
        # Check if ArgoCD is accessible
        if ! kubectl get application.argoproj.io -n argocd >/dev/null 2>&1; then
            sleep $check_interval
            continue
        fi
        
        # Get application status
        local app_status
        if ! app_status=$(kubectl get application.argoproj.io -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null); then
            sleep 10
            continue
        fi
        
        # Count applications
        local total_apps=$(echo "$app_status" | grep -v '^$' | wc -l)
        if [ "$total_apps" -eq 0 ]; then
            sleep $check_interval
            continue
        fi
        
        # Check health
        local healthy_apps=$(echo "$app_status" | awk '$2 == "Healthy" {count++} END {print count+0}')
        local critical_unhealthy=$(echo "$app_status" | awk '$2 != "Healthy" && $2 != "" {print $1}' | grep -v '^$' | wc -l)
        
        if [ "$critical_unhealthy" -eq 0 ] && [ "$total_apps" -gt 0 ]; then
            [ -n "$message_prefix" ] && echo "$message_prefix All $total_apps ArgoCD applications are healthy"
            return 0
        fi
        
        # Handle stuck operations and conflicts
        handle_stuck_operations 180 "$message_prefix"
        handle_revision_conflicts "$message_prefix"
        
        sleep $check_interval
    done
    
    return 1
}

delete_argocd_appsets() {
    # Remove BOOTSTRAP_APPS applicationsets & applications with finalizer patch
    for app in "${BOOTSTRAP_APPS[@]}"; do
        log "Deleting bootstrap applicationset: $app"
        kubectl delete applicationset.argoproj.io "$app" -n argocd --cascade=orphan --ignore-not-found=true 2>/dev/null || true

        log "Deleting bootstrap application: $app"
        kubectl patch application.argoproj.io "$app" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
        kubectl delete application.argoproj.io "$app" -n argocd --cascade=orphan --ignore-not-found=true 2>/dev/null || true
    done
    
    # Remove all remaining applicationsets with finalizer patch
    local all_appsets=$(kubectl get applicationsets -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")
    
    if [ -n "$all_appsets" ]; then
        echo "$all_appsets" | while read -r appset_name; do
            if [ -n "$appset_name" ]; then
                log "Deleting remaining applicationset: $appset_name"
                kubectl patch applicationset.argoproj.io "$appset_name" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
                kubectl delete applicationset.argoproj.io "$appset_name" -n argocd --cascade=orphan --ignore-not-found=true 2>/dev/null || true
            fi
        done
    fi
}

# Function to delete ArgoCD applications
delete_argocd_apps() {
    local app_list="$1"
    local mode="${2:-ignore}"  # "ignore" or "only"
    local timeout=${3:-120}
    
    # Get all applications with name and namespace
    local all_apps=$(kubectl get application.argoproj.io -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.namespace}{"\n"}{end}' 2>/dev/null || echo "")
    
    if [ -z "$all_apps" ]; then
        return 0
    fi

    echo "$all_apps" | while read -r app_name app_namespace; do
        if [ -n "$app_name" ] && [ -n "$app_namespace" ]; then
            local should_delete=false
            
            if [ "$mode" = "ignore" ]; then
                # Ignore mode: delete all except those in the list (partial match)
                local skip_app=false
                for pattern in $app_list; do
                    if echo "$app_name" | grep -q "$pattern"; then
                        echo "Skipping $app_name (matches ignore pattern: $pattern)"
                        skip_app=true
                        break
                    fi
                done
                [ "$skip_app" = "true" ] && continue
                should_delete=true
            elif [ "$mode" = "only" ]; then
                # Only mode: delete only those in the list (partial match)
                local match_found=false
                for pattern in $app_list; do
                    if echo "$app_name" | grep -q "$pattern"; then
                        match_found=true
                        break
                    fi
                done
                if [ "$match_found" = "true" ]; then
                    should_delete=true
                else
                    echo "Skipping $app_name (does not match any delete pattern)"
                    continue
                fi
            fi
            
            if [ "$should_delete" = "true" ]; then  
            log "Deleting ArgoCD application: $app_name"
            
            # Terminate any ongoing operations
            terminate_argocd_operation "$app_name"
            
            # Delete the application without waiting
            kubectl delete application.argoproj.io "$app_name" -n "$app_namespace" --wait=false 2>/dev/null || true
            
            # Wait for deletion with timeout
            local start_time=$(date +%s)
            local end_time=$((start_time + timeout))
            
            while [ $(date +%s) -lt $end_time ]; do
                if ! kubectl get application.argoproj.io "$app_name" -n "$app_namespace" >/dev/null 2>&1; then
                    log_success "Application $app_name deleted successfully"
                    break
                fi
                sleep 5
            done
            
            # Force delete if still exists
            if kubectl get application.argoproj.io "$app_name" -n "$app_namespace" >/dev/null 2>&1; then
                echo "Force deleting $app_name (timeout reached)"
                kubectl patch application.argoproj.io "$app_name" -n "$app_namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
                kubectl delete application.argoproj.io "$app_name" -n "$app_namespace" --force --grace-period=0 2>/dev/null || true
            fi
            fi
        fi
    done
}
