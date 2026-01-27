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
        
        # Always recalculate the domain to handle cases where it becomes available later
        # Calculate domain the same way as 1-tools-urls.sh
        local domain_name=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null)
        if [ -z "$domain_name" ] || [ "$domain_name" = "null" ]; then
            domain_name=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text 2>/dev/null)
        fi
        
        # Fallback to ARGOCD_URL environment variable if domain calculation fails
        if [ -z "$domain_name" ] || [ "$domain_name" = "None" ] || [ "$domain_name" = "null" ]; then
            if [ -n "$ARGOCD_URL" ]; then
                # Extract hostname from URL (remove https:// and /argocd)
                domain_name=$(echo "$ARGOCD_URL" | sed 's|https://||' | sed 's|/argocd||')
            fi
        fi
        
        argocd_server="$domain_name"
        
        if [ -n "$argocd_server" ] && [ "$argocd_server" != "None" ] && [ "$argocd_server" != "null" ]; then
            export ARGOCD_SERVER="$argocd_server"
            # Login using admin credentials with timeout
            if timeout 30 argocd login --username admin --password "${IDE_PASSWORD}" --grpc-web-root-path /argocd "$argocd_server" --insecure 2>/dev/null; then
                return 0
            fi
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

# Function to sync ArgoCD application in background (non-blocking)
sync_argocd_app_in_background() {
    local app_name=$1
    
    # Try ArgoCD CLI first if available and authenticated
    if authenticate_argocd; then
        print_info "Using ArgoCD CLI to sync $app_name (background)"
        argocd app sync "$app_name" &
    else
        print_warning "ArgoCD CLI authentication failed, using kubectl approach (background)"
        kubectl patch application.argoproj.io "$app_name" -n argocd --type='merge' -p='{"operation":{"sync":{}}}' &
    fi
}

# Function to sync ArgoCD application
sync_argocd_app() {
    local app_name=$1
    local force_flag=""
    
    # Check if app is already healthy and synced - skip if so
    local app_status=$(kubectl get application "$app_name" -n argocd -o json 2>/dev/null)
    if [ -n "$app_status" ]; then
        local health=$(echo "$app_status" | jq -r '.status.health.status // "Unknown"')
        local sync=$(echo "$app_status" | jq -r '.status.sync.status // "Unknown"')
        local operation_phase=$(echo "$app_status" | jq -r '.status.operationState.phase // "None"')
        
        # Check for revision mismatch errors in operation state
        local operation_message=$(echo "$app_status" | jq -r '.status.operationState.message // ""')
        local revision_mismatch=false
        if [[ "$operation_message" == *"cannot reference a different revision"* ]] || [[ "$operation_message" == *"ComparisonError"* ]]; then
            print_info "Detected revision mismatch in $app_name, applying complete fix..."
            terminate_argocd_operation "$app_name"
            sleep 2
            refresh_argocd_app "$app_name" "true"
            sleep 5
            revision_mismatch=true
        fi
        
        # Skip if already healthy and synced with no running operations (unless we just fixed revision mismatch)
        if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ] && [ "$operation_phase" != "Running" ] && [ "$revision_mismatch" = false ]; then
            print_info "App $app_name already healthy and synced, skipping sync"
            return 0
        fi
        
        # Skip if currently syncing (unless we just fixed revision mismatch)
        if [ "$operation_phase" = "Running" ] && [ "$revision_mismatch" = false ]; then
            print_info "App $app_name is currently syncing, skipping"
            return 0
        fi
        
        print_info "App $app_name needs sync (health: $health, sync: $sync, operation: $operation_phase)"
    fi
    
    # Force sync for keycloak to ensure PostSync hooks execute
    if [[ "$app_name" == *"keycloak"* ]]; then
        force_flag="--force"
        print_info "Using force sync for $app_name to execute PostSync hooks"
    fi
    
    # Try ArgoCD CLI first if available and authenticated
    if authenticate_argocd; then
        print_info "Using ArgoCD CLI to sync $app_name"
        argocd app sync "$app_name" $force_flag --timeout 200 || {
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
                # Force hard refresh for OutOfSync/Missing apps
                refresh_argocd_app "$app" "true"
                sleep 3
                sync_argocd_app "$app"
                sleep 2
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
                sleep 1
                sync_argocd_app "$app"
            fi
        done
    fi
    
    # Handle any apps stuck in operations or Progressing state for too long
    local stuck_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.items[] | select(
            ((.status.operationState.phase == "Running") or (.status.health.status == "Progressing")) and 
            ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 300)
        ) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$stuck_apps" ]; then
        echo "$stuck_apps" | while read -r app; do
            if [ -n "$app" ]; then
                print_info "Refreshing stuck application: $app"
                terminate_argocd_operation "$app"
                sleep 1
                refresh_argocd_app "$app" "true"
                sleep 2
                sync_argocd_app "$app" || true
                sleep 1
            fi
        done
    fi
}

# Wait for ArgoCD applications health (60min default timeout)
wait_for_argocd_apps_health() {
    local timeout=${1:-3600}
    local check_interval=${2:-30}
    local start_time=$(date +%s)
    local end_time=$((start_time + timeout))
    
    print_info "Waiting for ArgoCD applications to become healthy (timeout: ${timeout}s)..."
    
    while [ $(date +%s) -lt $end_time ]; do
        # Check if ArgoCD namespace exists
        if ! kubectl get namespace argocd >/dev/null 2>&1; then
            print_warning "ArgoCD namespace not found, waiting..."
            sleep $check_interval
            continue
        fi
        
        # Check if ArgoCD server is responding with comprehensive pod check
        local argocd_server_ready=0
        local argocd_pods_running=0
        
        # Check deployment ready replicas
        argocd_server_ready=$(kubectl get deployment -n argocd argocd-server -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        [ -z "$argocd_server_ready" ] && argocd_server_ready="0"
        
        # Also check actual pod status
        argocd_pods_running=$(kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server --no-headers 2>/dev/null | grep -c "1/1.*Running" || echo "0")
        
        if [ "$argocd_server_ready" -eq 0 ] || [ "$argocd_pods_running" -eq 0 ]; then
            print_warning "ArgoCD server not ready (deployment: $argocd_server_ready, running pods: $argocd_pods_running), waiting..."
            sleep $check_interval
            continue
        fi
        
        # Check if ArgoCD domain is available (recalculate each time with improved error handling)
        local domain_name=""
        local domain_available=false
        
        # Try to get domain from secret first
        domain_name=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null || echo "")
        
        # If not found in secret or empty, try CloudFront with timeout
        if [ -z "$domain_name" ] || [ "$domain_name" = "null" ] || [ "$domain_name" = "" ]; then
            domain_name=$(timeout 30 aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text 2>/dev/null || echo "")
        fi
        
        # Validate domain name
        if [ -n "$domain_name" ] && [ "$domain_name" != "None" ] && [ "$domain_name" != "null" ] && [ "$domain_name" != "" ]; then
            domain_available=true
            print_info "ArgoCD domain found: $domain_name"
        else
            print_warning "ArgoCD domain not available yet, waiting..."
            sleep $check_interval
            continue
        fi
        
        # Check if applications exist
        if ! kubectl get applications -n argocd >/dev/null 2>&1; then
            print_warning "No ArgoCD applications found yet, waiting..."
            sleep $check_interval
            continue
        fi
        
        local total_apps=0
        local healthy_apps=0
        local synced_apps=0
        local unhealthy_apps=()
        
        # Get application status with error handling and retries
        local app_status=""
        local retry_count=0
        while [ $retry_count -lt 3 ]; do
            if app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null); then
                break
            else
                print_warning "Failed to get application status (attempt $((retry_count + 1))/3), retrying..."
                sleep 10
                retry_count=$((retry_count + 1))
            fi
        done
        
        if [ $retry_count -eq 3 ]; then
            print_warning "Could not get application status after 3 attempts, continuing..."
            sleep $check_interval
            continue
        fi

        while IFS=' ' read -r app health sync; do
            [ -z "$app" ] && continue
            total_apps=$((total_apps + 1))
            
            # Handle missing health/sync status
            [ -z "$health" ] && health="Unknown"
            [ -z "$sync" ] && sync="Unknown"
            
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
        local sync_pct=0
        if [ $total_apps -gt 0 ]; then
            health_pct=$((healthy_apps * 100 / total_apps))
            sync_pct=$((synced_apps * 100 / total_apps))
        fi

        print_info "ArgoCD status: $healthy_apps/$total_apps healthy ($health_pct%), $synced_apps/$total_apps synced ($sync_pct%)"
        
        # Handle issues before checking success criteria
        handle_stuck_operations
        sleep 2
        handle_sync_issues
        
        # More lenient success criteria - accept 70% healthy and 60% synced
        if [ $total_apps -gt 0 ] && [ $health_pct -ge 70 ] && [ $sync_pct -ge 60 ]; then
            print_success "ArgoCD applications sufficiently healthy ($health_pct% healthy, $sync_pct% synced)"
            return 0
        fi
        
        # Show problematic apps for debugging
        if [ ${#unhealthy_apps[@]} -gt 0 ] && [ $(($(date +%s) - start_time)) -gt 300 ]; then
            print_warning "Problematic apps: ${unhealthy_apps[*]}"
        fi
        
        sleep $check_interval
    done
    
    print_error "Timeout waiting for ArgoCD applications health"
    return 1
}

# Dependency-aware ArgoCD app synchronization
wait_for_argocd_apps_with_dependencies() {
    print_info "Starting dependency-aware ArgoCD app synchronization..."
    
    # Phase 1: Wait for hub cluster core infrastructure (sync waves 0-30)
    kubectl config use-context "${RESOURCE_PREFIX}-hub"
    wait_for_sync_wave_completion "hub" 30
    
    # Phase 2: Verify hub Crossplane providers are healthy
    wait_for_hub_crossplane_ready
    
    # Phase 3: Wait for spoke clusters basic infrastructure (waves 0-20)
    for cluster_name in "${CLUSTER_NAMES[@]}"; do
        if [[ "$cluster_name" != *"hub"* ]]; then
            kubectl config use-context "$cluster_name"
            wait_for_sync_wave_completion "$cluster_name" 20
        fi
    done
    
    # Phase 4: Wait for spoke Crossplane providers (wave 25-30)
    for cluster_name in "${CLUSTER_NAMES[@]}"; do
        if [[ "$cluster_name" != *"hub"* ]]; then
            kubectl config use-context "$cluster_name"
            wait_for_sync_wave_completion "$cluster_name" 30
        fi
    done
    
    # Phase 5: Final health check for all remaining apps
    kubectl config use-context "${RESOURCE_PREFIX}-hub"
    wait_for_remaining_apps_health
}

wait_for_sync_wave_completion() {
    local cluster=$1
    local max_wave=$2
    local timeout=1800  # 30 minutes per phase
    
    print_info "[$cluster] Waiting for sync waves 0-$max_wave to complete..."
    
    local start_time=$(date +%s)
    while [ $(($(date +%s) - start_time)) -lt $timeout ]; do
        local pending_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
            jq -r --arg max_wave "$max_wave" \
            '.items[] | select(
                ((.metadata.annotations."argocd.argoproj.io/sync-wave" // "0") | tonumber) <= ($max_wave | tonumber) and
                ((.status.sync.status != "Synced" or .status.health.status != "Healthy") and
                 (.status.operationState.phase // "None") != "Running")
            ) | .metadata.name' 2>/dev/null)
        
        # Filter out best effort apps from blocking
        local blocking_apps=""
        for app in $pending_apps; do
            local is_best_effort=false
            for best_effort_app in "${BEST_EFFORT_APPS[@]}"; do
                if [[ "$app" == "$best_effort_app" ]]; then
                    is_best_effort=true
                    print_info "[$cluster] Syncing best effort app: $app (non-blocking)"
                    sync_argocd_app_in_background "$app"
                    break
                fi
            done
            if [[ "$is_best_effort" == false ]]; then
                blocking_apps="$blocking_apps $app"
            fi
        done
        
        if [ -z "$blocking_apps" ]; then
            print_success "[$cluster] Sync waves 0-$max_wave completed (ignoring best effort apps)"
            return 0
        fi
        
        # Check for stuck apps and recover (both stuck operations and stuck Progressing)
        local stuck_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
            jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            '.items[] | select(
                ((.status.operationState.phase == "Running") or (.status.health.status == "Progressing")) and 
                ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 300)
            ) | .metadata.name' 2>/dev/null || echo "")
        
        if [ -n "$stuck_apps" ]; then
            echo "$stuck_apps" | while read -r app; do
                if [ -n "$app" ]; then
                    print_info "[$cluster] Recovering stuck app: $app"
                    terminate_argocd_operation "$app"
                    sleep 1
                    refresh_argocd_app "$app" "true"
                    sleep 2
                    sync_argocd_app "$app" || true
                    sleep 1
                fi
            done
        fi
        
        # Try to sync remaining problematic apps
        for app in $blocking_apps; do
            if [ -n "$app" ]; then
                print_info "[$cluster] Syncing blocking app: $app"
                sync_argocd_app "$app" || true
            fi
        done
        
        print_info "[$cluster] Waiting for: $blocking_apps"
        sleep 30
    done
    
    print_warning "[$cluster] Timeout waiting for sync waves 0-$max_wave"
    return 1
}

wait_for_hub_crossplane_ready() {
    print_info "[hub] Verifying Crossplane providers are healthy..."
    
    local timeout=600  # 10 minutes
    local start_time=$(date +%s)
    
    while [ $(($(date +%s) - start_time)) -lt $timeout ]; do
        local unhealthy_providers=$(kubectl get providers -n crossplane-system --no-headers 2>/dev/null | \
            grep -v "True.*True" | wc -l)
        
        if [ "$unhealthy_providers" -eq 0 ]; then
            print_success "[hub] All Crossplane providers are healthy"
            return 0
        fi
        
        print_info "[hub] $unhealthy_providers Crossplane providers still unhealthy"
        sleep 30
    done
    
    print_warning "[hub] Timeout waiting for Crossplane providers"
    return 1
}

wait_for_remaining_apps_health() {
    print_info "Final cleanup: syncing remaining unhealthy applications..."
    
    # Get apps that are not healthy (excluding best effort apps)
    local unhealthy_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(
            .status.health.status != "Healthy"
        ) | .metadata.name' 2>/dev/null)
    
    if [ -n "$unhealthy_apps" ]; then
        print_info "Found unhealthy apps, attempting final sync..."
        echo "$unhealthy_apps" | while read -r app; do
            if [ -n "$app" ]; then
                local is_best_effort=false
                for best_effort_app in "${BEST_EFFORT_APPS[@]}"; do
                    if [[ "$app" == "$best_effort_app" ]]; then
                        is_best_effort=true
                        break
                    fi
                done
                
                if [[ "$is_best_effort" == false ]]; then
                    print_info "Final sync attempt for unhealthy app: $app"
                    sync_argocd_app "$app" || true
                    sleep 10
                fi
            fi
        done
        
        print_info "Waiting for final sync operations to complete..."
        sleep 60
    fi
    
    print_success "Final cleanup completed"
    return 0
}

show_final_status() {
    print_info "Waiting for any ongoing sync operations to complete..."
    
    # First, immediately handle any apps with ComparisonError
    local comparison_error_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(
            (.status.operationState.phase == "Running") and
            ((.status.operationState.message // "") | contains("ComparisonError") or contains("cannot reference a different revision"))
        ) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$comparison_error_apps" ]; then
        print_warning "Found apps with ComparisonError that will never recover, terminating immediately..."
        echo "$comparison_error_apps" | while read -r app; do
            if [ -n "$app" ]; then
                # Check if it's a best effort app
                local is_best_effort=false
                for best_effort_app in "${BEST_EFFORT_APPS[@]}"; do
                    if [[ "$app" == "$best_effort_app" ]]; then
                        is_best_effort=true
                        break
                    fi
                done
                
                print_warning "Terminating ComparisonError operation for $app"
                terminate_argocd_operation "$app"
                sleep 10
                refresh_argocd_app "$app" "true"
                sleep 10
                
                if [[ "$is_best_effort" == true ]]; then
                    sync_argocd_app_in_background "$app"
                else
                    sync_argocd_app "$app"
                fi
            fi
        done
        sleep 15  # Give time for sync operations to start properly
    fi
    
    # Wait for any running sync operations to finish
    local max_wait=300  # 5 minutes
    local wait_time=0
    
    while [ $wait_time -lt $max_wait ]; do
        local running_syncs=$(kubectl get applications -n argocd -o json 2>/dev/null | \
            jq -r '.items[] | select(.status.operationState.phase == "Running") | .metadata.name' 2>/dev/null || echo "")
        
        # Filter out best effort apps from blocking wait
        local blocking_running_syncs=""
        for app in $running_syncs; do
            local is_best_effort=false
            for best_effort_app in "${BEST_EFFORT_APPS[@]}"; do
                if [[ "$app" == "$best_effort_app" ]]; then
                    is_best_effort=true
                    break
                fi
            done
            if [[ "$is_best_effort" == false ]]; then
                blocking_running_syncs="$blocking_running_syncs $app"
            fi
        done
        
        if [ -z "$blocking_running_syncs" ]; then
            print_info "All blocking sync operations completed"
            break
        fi
        
        print_info "Waiting for sync operations: $(echo $blocking_running_syncs | tr '\n' ' ')"
        sleep 10
        wait_time=$((wait_time + 10))
    done
    
    if [ $wait_time -ge $max_wait ]; then
        print_warning "Timeout waiting for sync operations, showing current status..."
    fi
    
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

# Function to force sync all ArgoCD applications
force_sync_all_apps() {
    print_info "Force syncing all ArgoCD applications..."
    
    if ! kubectl get applications -n argocd >/dev/null 2>&1; then
        print_warning "No ArgoCD applications found"
        return 1
    fi
    
    kubectl get applications -n argocd -o name 2>/dev/null | while read app; do
        app_name=$(basename "$app")
        print_info "Force syncing $app_name..."
        terminate_argocd_operation "$app_name"
        sleep 1
        refresh_argocd_app "$app_name" "true"
        sleep 1
        sync_argocd_app "$app_name"
    done
    
    print_success "Completed force sync of all applications"
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
    
    # Collect apps to delete
    local apps_to_delete=()
    
    while read -r namespace name _; do
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
        
        apps_to_delete+=("$namespace:$name")
    done <<< "$all_apps"
    
    # Phase 1: Initiate deletion for all apps in parallel
    log "Initiating deletion of ${#apps_to_delete[@]} applications..."
    for app in "${apps_to_delete[@]}"; do
        local namespace="${app%%:*}"
        local name="${app##*:}"
        
        # Remove finalizers if required
        if [[ "$patch_required" == "true" ]]; then
            kubectl patch application.argoproj.io "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
        fi
        
        terminate_argocd_operation "$name" # Terminate any ongoing operation
        kubectl delete application.argoproj.io "$name" -n "$namespace" --wait=false 2>/dev/null || true
    done
    
    # Phase 2: Wait for deletions with reduced timeout
    local delete_timeout=15  # 15 seconds - apps that can delete will do so quickly
    local delete_start=$(date +%s)
    
    log "Waiting for applications to delete (timeout: ${delete_timeout}s)..."
    while true; do
        local remaining_apps=()
        
        for app in "${apps_to_delete[@]}"; do
            local namespace="${app%%:*}"
            local name="${app##*:}"
            
            if kubectl get application.argoproj.io "$name" -n "$namespace" >/dev/null 2>&1; then
                remaining_apps+=("$app")
            fi
        done
        
        # If no apps remaining, we're done
        if [[ ${#remaining_apps[@]} -eq 0 ]]; then
            log "All applications deleted successfully"
            break
        fi
        
        # Check timeout
        local elapsed=$(($(date +%s) - delete_start))
        if [ $elapsed -ge $delete_timeout ]; then
            log "Timeout reached. Force deleting ${#remaining_apps[@]} stuck applications..."
            for app in "${remaining_apps[@]}"; do
                local namespace="${app%%:*}"
                local name="${app##*:}"
                
                log "Force deleting: $name"
                kubectl patch application.argoproj.io "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
                kubectl delete application.argoproj.io "$name" -n "$namespace" --force --grace-period=0 2>/dev/null || true
            done
            break
        fi
        
        sleep 2
        apps_to_delete=("${remaining_apps[@]}")
    done
}
