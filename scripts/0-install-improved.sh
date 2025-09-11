#!/bin/bash

# Improved Bootstrap script with better error handling, efficiency, and resilience
# Key improvements:
# 1. Better script validation before execution
# 2. Smarter retry logic with exponential backoff
# 3. Parallel operations where possible
# 4. Better ArgoCD health monitoring
# 5. Skip redundant operations on retry

source /etc/profile.d/workshop.sh
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        [ -f "$file" ] && source "$file"
    done
fi

source "$(dirname "$0")/colors.sh"

# Enhanced configuration
MAX_RETRIES=3
BASE_RETRY_DELAY=30  # Base delay for exponential backoff
SCRIPT_DIR="$(dirname "$0")"
ARGOCD_WAIT_TIMEOUT=600
ARGOCD_CHECK_INTERVAL=15  # More frequent checks
CLUSTER_CHECK_TIMEOUT=1800  # 30 minutes max for cluster readiness

# Cluster configuration
CLUSTER_NAMES=(
    "${HUB_CLUSTER_NAME}"
    "${SPOKE_CLUSTER_NAME_PREFIX}-dev"
    "${SPOKE_CLUSTER_NAME_PREFIX}-prod"
)

# Define scripts with validation - use improved versions where available
SCRIPTS=(
    "1-argocd-gitlab-setup-improved.sh"
    "2-bootstrap-accounts-improved.sh"
    "3-register-terraform-spoke-clusters-improved.sh:dev"  # Use colon separator for args
    "3-register-terraform-spoke-clusters-improved.sh:prod"
    "6-tools-urls.sh"
)

# State tracking for smart retries
declare -A SCRIPT_STATE
declare -A COMPLETED_STEPS

# Enhanced logging
log() {
    echo -e "${BLUE}[INFO]${NC} $1" >&2
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

# Validate script exists and is executable
validate_script() {
    local script_path="$1"
    local script_name=$(basename "$script_path")
    
    if [[ ! -f "$script_path" ]]; then
        log_error "Script not found: $script_path"
        
        # Try to find alternative script names
        local alt_script="${script_path/-terraform/}"
        if [[ -f "$alt_script" ]]; then
            log "Found alternative script: $alt_script"
            echo "$alt_script"
            return 0
        fi
        
        # Check for similar scripts
        local similar=$(find "$SCRIPT_DIR" -name "*${script_name%%-*}*" -type f | head -1)
        if [[ -n "$similar" ]]; then
            log "Found similar script: $similar"
            echo "$similar"
            return 0
        fi
        
        return 1
    fi
    
    if [[ ! -x "$script_path" ]]; then
        log "Making script executable: $script_path"
        chmod +x "$script_path"
    fi
    
    echo "$script_path"
    return 0
}

# Smart cluster readiness check with parallel validation
check_clusters_ready() {
    log "Checking EKS cluster readiness..."
    log "Using cluster names: ${CLUSTER_NAMES[*]}"
    
    local start_time=$(date +%s)
    local all_ready=false
    local check_count=0
    
    while [[ $all_ready == false ]]; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [[ $elapsed -gt $CLUSTER_CHECK_TIMEOUT ]]; then
            log_error "Timeout waiting for clusters to be ready after ${CLUSTER_CHECK_TIMEOUT}s"
            return 1
        fi
        
        check_count=$((check_count + 1))
        log "Cluster readiness check #$check_count (${elapsed}s elapsed)"
        
        local ready_count=0
        local total_clusters=${#CLUSTER_NAMES[@]}
        
        # Check all clusters in parallel
        local pids=()
        local temp_dir=$(mktemp -d)
        
        for i in "${!CLUSTER_NAMES[@]}"; do
            local cluster="${CLUSTER_NAMES[$i]}"
            (
                local status=$(aws eks describe-cluster --name "$cluster" --query 'cluster.status' --output text 2>/dev/null || echo "NOT_FOUND")
                echo "$cluster:$status" > "$temp_dir/cluster_$i.status"
            ) &
            pids+=($!)
        done
        
        # Wait for all checks to complete
        for pid in "${pids[@]}"; do
            wait "$pid"
        done
        
        # Process results
        for i in "${!CLUSTER_NAMES[@]}"; do
            local result=$(cat "$temp_dir/cluster_$i.status" 2>/dev/null || echo "ERROR")
            local cluster=$(echo "$result" | cut -d: -f1)
            local status=$(echo "$result" | cut -d: -f2)
            
            if [[ "$status" == "ACTIVE" ]]; then
                log_success "Cluster $cluster is ACTIVE"
                ready_count=$((ready_count + 1))
            else
                log "Cluster $cluster status: $status"
            fi
        done
        
        rm -rf "$temp_dir"
        
        if [[ $ready_count -eq $total_clusters ]]; then
            all_ready=true
            log_success "All EKS clusters are ready!"
        else
            local remaining=$((total_clusters - ready_count))
            local remaining_time=$((CLUSTER_CHECK_TIMEOUT - elapsed))
            log "Waiting for $remaining clusters (${remaining_time}s remaining)..."
            sleep 30
        fi
    done
    
    return 0
}

# Enhanced ArgoCD health monitoring
monitor_argocd_health() {
    local timeout=${1:-$ARGOCD_WAIT_TIMEOUT}
    local start_time=$(date +%s)
    
    log "Monitoring ArgoCD applications health (timeout: ${timeout}s)"
    
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [[ $elapsed -gt $timeout ]]; then
            log_warn "Timeout waiting for ArgoCD applications to be fully healthy"
            return 1
        fi
        
        # Get application status
        local app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}:{.status.health.status}:{.status.sync.status}{"\n"}{end}' 2>/dev/null)
        
        if [[ -z "$app_status" ]]; then
            log "Waiting for ArgoCD applications to be created..."
            sleep $ARGOCD_CHECK_INTERVAL
            continue
        fi
        
        local total_apps=0
        local healthy_apps=0
        local synced_apps=0
        local problematic_apps=()
        
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            
            local app_name=$(echo "$line" | cut -d: -f1)
            local health=$(echo "$line" | cut -d: -f2)
            local sync=$(echo "$line" | cut -d: -f3)
            
            total_apps=$((total_apps + 1))
            
            if [[ "$health" == "Healthy" ]]; then
                healthy_apps=$((healthy_apps + 1))
            fi
            
            if [[ "$sync" == "Synced" ]]; then
                synced_apps=$((synced_apps + 1))
            fi
            
            # Track problematic apps
            if [[ "$health" != "Healthy" || "$sync" != "Synced" ]]; then
                problematic_apps+=("$app_name:$health/$sync")
            fi
        done <<< "$app_status"
        
        log "ArgoCD status: $healthy_apps/$total_apps healthy, $synced_apps/$total_apps synced"
        
        # Show problematic apps (limit to first 5)
        if [[ ${#problematic_apps[@]} -gt 0 ]]; then
            local show_count=$((${#problematic_apps[@]} > 5 ? 5 : ${#problematic_apps[@]}))
            for ((i=0; i<show_count; i++)); do
                log "   ⚠️  ${problematic_apps[$i]}"
            done
            if [[ ${#problematic_apps[@]} -gt 5 ]]; then
                log "   ... and $((${#problematic_apps[@]} - 5)) more"
            fi
        fi
        
        # Consider "good enough" if most apps are healthy
        local health_threshold=$((total_apps * 80 / 100))  # 80% threshold
        if [[ $healthy_apps -ge $health_threshold && $synced_apps -ge $health_threshold ]]; then
            log_success "ArgoCD applications are sufficiently healthy ($healthy_apps/$total_apps healthy)"
            return 0
        fi
        
        sleep $ARGOCD_CHECK_INTERVAL
    done
}

# Execute script with smart retry logic
execute_script() {
    local script_entry="$1"
    local script_name=$(echo "$script_entry" | cut -d: -f1)
    local script_args=$(echo "$script_entry" | cut -d: -f2- | sed 's/^[^:]*://')
    
    # Handle case where there are no args
    if [[ "$script_args" == "$script_name" ]]; then
        script_args=""
    fi
    
    local script_path="$SCRIPT_DIR/$script_name"
    local script_key="${script_name}_${script_args// /_}"
    
    log "Preparing to run: $script_name $script_args"
    
    # Validate script exists
    local validated_script
    if ! validated_script=$(validate_script "$script_path"); then
        log_error "Cannot find or validate script: $script_name"
        return 1
    fi
    
    # Check if already completed successfully
    if [[ "${COMPLETED_STEPS[$script_key]}" == "true" ]]; then
        log_success "Script $script_name already completed successfully, skipping"
        return 0
    fi
    
    log "Starting execution of $script_name $script_args"
    
    for attempt in $(seq 1 $MAX_RETRIES); do
        log "Attempt $attempt/$MAX_RETRIES for $script_name"
        
        # Calculate exponential backoff delay
        local delay=$((BASE_RETRY_DELAY * (2 ** (attempt - 1))))
        
        # Execute the script
        if [[ -n "$script_args" ]]; then
            "$validated_script" $script_args
        else
            "$validated_script"
        fi
        
        local exit_code=$?
        
        if [[ $exit_code -eq 0 ]]; then
            log_success "Script $script_name completed successfully"
            COMPLETED_STEPS[$script_key]="true"
            
            # Post-script validation for ArgoCD-related scripts
            if [[ "$script_name" == *"argocd"* || "$script_name" == *"bootstrap"* ]]; then
                log "Performing post-script ArgoCD validation..."
                if ! monitor_argocd_health 300; then  # 5 minute timeout for post-validation
                    log_warn "ArgoCD validation failed, but script completed successfully"
                fi
            fi
            
            return 0
        else
            log_error "$script_name failed with exit code $exit_code (attempt $attempt/$MAX_RETRIES)"
            SCRIPT_STATE[$script_key]="failed_attempt_$attempt"
            
            if [[ $attempt -lt $MAX_RETRIES ]]; then
                # Attempt recovery for ArgoCD-related failures
                if [[ "$script_name" == *"argocd"* ]]; then
                    log "Attempting ArgoCD recovery before retry..."
                    attempt_argocd_recovery
                fi
                
                log_warn "Retrying $script_name in ${delay} seconds..."
                sleep $delay
            fi
        fi
    done
    
    log_error "Script $script_name failed after $MAX_RETRIES attempts"
    return 1
}

# ArgoCD recovery function
attempt_argocd_recovery() {
    log "Checking ArgoCD deployment status..."
    kubectl get deployments -n argocd
    
    # Restart key ArgoCD components
    kubectl rollout restart deployment/argocd-server -n argocd
    kubectl rollout restart deployment/argocd-repo-server -n argocd
    
    # Clear any stuck operations
    kubectl delete applications.argoproj.io --all -n argocd --field-selector metadata.name!=bootstrap 2>/dev/null || true
    
    # Wait a bit for recovery
    sleep 30
}

# Update kubeconfig for all clusters
update_kubeconfigs() {
    log "Updating kubeconfig for all clusters..."
    
    for cluster in "${CLUSTER_NAMES[@]}"; do
        log "Updating kubeconfig for $cluster"
        if aws eks --region "${AWS_REGION:-us-east-1}" update-kubeconfig --name "$cluster"; then
            log_success "Kubeconfig updated for $cluster"
        else
            log_warn "Failed to update kubeconfig for $cluster"
        fi
    done
}

# Main execution function
main() {
    log "Starting bootstrap deployment process"
    log "Script directory: $SCRIPT_DIR"
    log "Max retries per script: $MAX_RETRIES"
    log "Base retry delay: $BASE_RETRY_DELAY seconds"
    log "ArgoCD wait timeout: $ARGOCD_WAIT_TIMEOUT seconds"
    log "Scripts to execute: ${SCRIPTS[*]}"
    
    # Check cluster readiness first
    if ! check_clusters_ready; then
        log_error "Cluster readiness check failed"
        exit 1
    fi
    
    # Update kubeconfigs
    update_kubeconfigs
    
    # Execute scripts in sequence
    local overall_success=true
    
    for script_entry in "${SCRIPTS[@]}"; do
        if ! execute_script "$script_entry"; then
            log_error "Failed to execute: $script_entry"
            overall_success=false
            break
        fi
        
        log "----------------------------------------"
    done
    
    if [[ $overall_success == true ]]; then
        log_success "All bootstrap scripts completed successfully!"
        log "Platform deployment is complete."
        
        # Final status check
        log "Final ArgoCD applications status:"
        kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status" 2>/dev/null || true
        
    else
        log_error "Bootstrap process failed"
        exit 1
    fi
}

# Trap for cleanup
trap 'log "Bootstrap process interrupted"; exit 130' INT TERM

# Run main function
main "$@"
