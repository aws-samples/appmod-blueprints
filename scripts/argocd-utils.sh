#!/bin/bash

# Shared ArgoCD utility functions
# Source this file in other scripts: source "$(dirname "$0")/argocd-utils.sh"

# Function to terminate ArgoCD application operations
terminate_argocd_operation() {
    local app_name=$1
    local use_grpc_web=${2:-true}
    
    if [ "$use_grpc_web" = "true" ]; then
        argocd app terminate-op "$app_name" --grpc-web 2>/dev/null || argocd app terminate-op "$app_name" 2>/dev/null || {
            kubectl delete operation -n argocd -l app.kubernetes.io/instance="$app_name" 2>/dev/null || true
        }
    else
        argocd app terminate-op "$app_name" 2>/dev/null || {
            kubectl delete operation -n argocd -l app.kubernetes.io/instance="$app_name" 2>/dev/null || true
        }
    fi
}

# Function to refresh ArgoCD application
refresh_argocd_app() {
    local app_name=$1
    local hard_refresh=${2:-true}
    local use_grpc_web=${3:-true}
    
    local refresh_args=""
    [ "$hard_refresh" = "true" ] && refresh_args="--hard"
    
    if [ "$use_grpc_web" = "true" ]; then
        argocd app refresh "$app_name" --grpc-web $refresh_args 2>/dev/null || argocd app refresh "$app_name" $refresh_args 2>/dev/null || true
    else
        argocd app refresh "$app_name" $refresh_args 2>/dev/null || true
    fi
}

# Function to sync ArgoCD application
sync_argocd_app() {
    local app_name=$1
    local timeout=${2:-60}
    local use_grpc_web=${3:-true}
    
    if [ "$use_grpc_web" = "true" ]; then
        argocd app sync "$app_name" --grpc-web --timeout "$timeout" 2>/dev/null || argocd app sync "$app_name" --timeout "$timeout" 2>/dev/null || true
    else
        argocd app sync "$app_name" --timeout "$timeout" 2>/dev/null || true
    fi
}

# Function to handle stuck ArgoCD operations
handle_stuck_operations() {
    local timeout_seconds=${1:-180}
    local message_prefix=${2:-""}
    
    local stuck_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
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
    
    local error_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
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
        if ! kubectl get applications -n argocd >/dev/null 2>&1; then
            sleep $check_interval
            continue
        fi
        
        # Get application status
        local app_status
        if ! app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null); then
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
