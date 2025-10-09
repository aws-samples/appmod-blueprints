#!/bin/bash

# Robust ArgoCD utility functions

export CORE_APPS=(
    "external-secrets"
    "argocd"
    "gitlab"
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

# Wait for ArgoCD applications health (30min default timeout)
wait_for_argocd_apps_health() {
    local timeout=${1:-1800}
    local check_interval=${2:-30}
    local start_time=$(date +%s)
    local end_time=$((start_time + timeout))
    
    while [ $(date +%s) -lt $end_time ]; do
        if ! kubectl get applications -n argocd >/dev/null 2>&1; then
            sleep $check_interval
            continue
        fi
        
        local total_apps=0
        local healthy_apps=0
        local synced_apps=0
        local unhealthy_apps=()
        
        local app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null)

        while IFS=' ' read -r app health sync; do
            [ -z "$app" ] && continue
            total_apps=$((total_apps + 1))
            
            if [ "$health" = "Healthy" ]; then
                healthy_apps=$((healthy_apps + 1))
            fi
            
            if [ "$sync" = "Synced" ]; then
                synced_apps=$((synced_apps + 1))
            fi
            
            # Track unhealthy apps for syncing
            if [ "$health" != "Healthy" ] || [ "$sync" = "OutOfSync" ]; then
                unhealthy_apps+=("$app")
            fi
        done <<< "$app_status"

        local health_pct=0
        if [ $total_apps -gt 0 ]; then
            health_pct=$((healthy_apps * 100 / total_apps))
        fi

        print_info "ArgoCD status: $healthy_apps/$total_apps healthy ($health_pct%), $synced_apps/$total_apps synced"
        
        # Accept 80% healthy as success
        if [ $health_pct -ge 80 ] && [ $synced_apps -ge $((total_apps * 70 / 100)) ]; then
            print_success "ArgoCD applications sufficiently healthy ($health_pct% healthy)"
            return 0
        fi
        
        handle_stuck_operations
        sleep 2
        handle_revision_conflicts
        sleep $check_interval
    done
    
    print_error "Timeout waiting for ArgoCD applications health"
    return 1
}

# Function to show final status
show_final_status() {
    print_info "Final ArgoCD Applications Status:"
    echo "----------------------------------------"
    
    if kubectl get applications -n argocd >/dev/null 2>&1; then
        kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status" --no-headers | \
        while read name sync health; do
            if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ]; then
                print_success "$name: $sync/$health"
            elif [ "$health" = "Healthy" ]; then
                print_warning "$name: $sync/$health"
            else
                print_error "$name: $sync/$health"
            fi
        done
    else
        print_error "Cannot access ArgoCD applications"
    fi
    
    echo "----------------------------------------"
}

delete_argocd_appsets() {
    if kubectl get crd applicationsets.argoproj.io >/dev/null 2>&1; then
        kubectl get applicationsets.argoproj.io --all-namespaces --no-headers 2>/dev/null | while read -r namespace name _; do
            kubectl delete applicationsets.argoproj.io "$name" -n "$namespace" --cascade=orphan 2>/dev/null || true
        done
        return 0
    fi
    log "No ArgoCD ApplicationSets found..."
}

delete_argocd_apps() {
    local partial_names_str="$1"
    local action="${2:-delete}"  # delete or ignore
    local patch_required="${3:-false}"  # whether to patch finalizers
    
    local all_apps=$(kubectl get applications.argoproj.io --all-namespaces --no-headers 2>/dev/null)
    
    if [[ -z "$all_apps" ]]; then
        log "No ArgoCD Applications found..."
        return 0
    fi
    
    # Process all apps
    echo "$all_apps" | while read -r namespace name _; do
        local should_process=false
        
        # Check if app matches any partial name (convert string to words)
        for partial in $partial_names_str; do
            if [[ -n "$partial" && "$name" == *"$partial"* ]]; then
                should_process=true
                break
            fi
        done
        
        # Process based on action
        if [[ "$action" == "ignore" && "$should_process" == "true" ]]; then
            continue
        elif [[ "$action" == "delete" && "$should_process" == "false" ]]; then
            continue
        fi
        
        # Remove finalizers if required
        if [[ "$patch_required" == "true" ]]; then
            kubectl patch application.argoproj.io "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
        fi
        
        terminate_argocd_operation "$name" # Terminate any ongoing operation
        kubectl delete application.argoproj.io "$name" -n "$namespace" --wait=false 2>/dev/null || true
        
        # Wait for deletion with 5 minute timeout
        local delete_start=$(date +%s)
        local delete_timeout=120  # 2 minutes
        
        while kubectl get application.argoproj.io "$name" -n "$namespace" >/dev/null 2>&1; do
            local elapsed=$(($(date +%s) - delete_start))
            if [ $elapsed -ge $delete_timeout ]; then
                log "Force deleting stuck application: $name"
                kubectl patch application.argoproj.io "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
                kubectl delete application.argoproj.io "$name" -n "$namespace" --force --grace-period=0 2>/dev/null || true
                break
            fi
            sleep 5
        done
    done
}
