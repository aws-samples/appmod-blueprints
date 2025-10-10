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

# Function to authenticate ArgoCD CLI
authenticate_argocd() {
    if command -v argocd >/dev/null 2>&1; then
        local argocd_server=""
        
        # Try to use existing ARGOCD_URL environment variable first
        if [ -n "$ARGOCD_URL" ]; then
            # Extract hostname from URL (remove https:// and /argocd)
            argocd_server=$(echo "$ARGOCD_URL" | sed 's|https://||' | sed 's|/argocd||')
        else
            # Calculate domain the same way as 1-tools-urls.sh
            local domain_name=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null)
            if [ -z "$domain_name" ]; then
                domain_name=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text)
            fi
            argocd_server="$domain_name"
        fi
        
        if [ -n "$argocd_server" ]; then
            export ARGOCD_SERVER="$argocd_server"
            # Login using admin credentials
            argocd login --username admin --password "${IDE_PASSWORD}" --grpc-web-root-path /argocd "$argocd_server"
            return $?
        fi
    fi
    return 1
}

# Function to terminate ArgoCD application operations
terminate_argocd_operation() {
    local app_name=$1
    
    # Try ArgoCD CLI first if available and authenticated
    if authenticate_argocd; then
        print_info "Using ArgoCD CLI to terminate operation for $app_name"
        argocd app terminate-op "$app_name" || {
            print_warning "ArgoCD CLI terminate failed, using direct kubectl approach"
            # Remove the operationState entirely - this is more effective
            kubectl patch application.argoproj.io "$app_name" -n argocd --type='json' -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
        }
    else
        print_warning "ArgoCD CLI authentication failed, using direct kubectl approach"
        # Remove the operationState entirely - this is more effective than setting operation to null
        kubectl patch application.argoproj.io "$app_name" -n argocd --type='json' -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
    fi
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
    
    # Try ArgoCD CLI first if available and authenticated
    if authenticate_argocd; then
        print_info "Using ArgoCD CLI to sync $app_name"
        argocd app sync "$app_name" --timeout 200 || {
            print_warning "ArgoCD CLI sync failed, falling back to kubectl"
            kubectl patch application.argoproj.io "$app_name" -n argocd --type='merge' -p='{"operation":{"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
        }
    else
        print_warning "ArgoCD CLI authentication failed, using kubectl"
        kubectl patch application.argoproj.io "$app_name" -n argocd --type='merge' -p='{"operation":{"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
    fi
}

# Handle stuck operations (terminate if running > 3 mins)
handle_stuck_operations() {
    # Get stuck operations using both methods for better detection
    local stuck_apps_jq=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.items[] | select(.status.operationState?.phase == "Running" and (.status.operationState.startedAt | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 180)) | .metadata.name' 2>/dev/null || echo "")
    
    # Also check with simpler method for very old operations
    local stuck_apps_simple=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.operationState.phase}{" "}{.status.operationState.startedAt}{"\n"}{end}' 2>/dev/null | \
        awk -v now=$(date +%s) '$2=="Running" && (now - mktime(gensub(/[-T:Z]/, " ", "g", $3))) > 180 {print $1}')
    
    # Combine both results
    local all_stuck_apps=$(echo -e "$stuck_apps_jq\n$stuck_apps_simple" | sort -u | grep -v '^$')
    
    if [ -n "$all_stuck_apps" ]; then
        echo "$all_stuck_apps" | while read -r app; do
            if [ -n "$app" ]; then
                print_warning "Terminating stuck operation for $app (running > 3 minutes)"
                terminate_argocd_operation "$app"
                sleep 2
                refresh_argocd_app "$app"
            fi
        done
    fi
}

# Handle sync issues (revision conflicts and OutOfSync applications)
handle_sync_issues() {
    # Get apps with revision conflicts OR OutOfSync/Missing status (often related issues)
    local problem_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(
            (.status.conditions[]? | select(.type == "ComparisonError" and (.message | contains("cannot reference a different revision")))) or
            (.status.sync.status == "OutOfSync" and .status.health.status == "Missing")
        ) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$problem_apps" ]; then
        echo "$problem_apps" | while read -r app; do
            if [ -n "$app" ]; then
                print_info "Fixing revision/sync issues for $app"
                terminate_argocd_operation "$app"
                sleep 2
                refresh_argocd_app "$app"
                sync_argocd_app "$app"
            fi
        done
    fi
    
    # Handle OutOfSync/Healthy apps (just need refresh and sync)
    local outofsync_healthy=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.sync.status == "OutOfSync" and .status.health.status == "Healthy") | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$outofsync_healthy" ]; then
        echo "$outofsync_healthy" | while read -r app; do
            if [ -n "$app" ]; then
                print_info "Syncing OutOfSync/Healthy application: $app"
                refresh_argocd_app "$app"
                sync_argocd_app "$app"
            fi
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
        
        # Handle issues before checking success criteria
        handle_stuck_operations
        sleep 2
        handle_sync_issues
        
        # Accept 80% healthy as success
        if [ $health_pct -ge 80 ] && [ $synced_apps -ge $((total_apps * 70 / 100)) ]; then
            print_success "ArgoCD applications sufficiently healthy ($health_pct% healthy)"
            return 0
        fi
        
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
