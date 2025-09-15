#!/bin/bash

# Bootstrap script to run deployment scripts in order with retry logic
# Runs: 1-argocd-gitlab-setup.sh, 2-bootstrap-accounts.sh, 3-register-terraform-spoke-clusters.sh (dev/prod), and 6-tools-urls.sh in sequence
# Each script must succeed before proceeding to the next

# Removed set -e to allow proper error handling in cluster waiting logic

#be sure we source env var
source /etc/profile.d/workshop.sh
# Source all environment files in .bashrc.d
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        if [ -f "$file" ]; then
            source "$file"
        fi
    done
fi

# Source colors for output formatting
source "$(dirname "$0")/colors.sh"

# Configuration
MAX_RETRIES=3
RETRY_DELAY=45  # Increased from 30 to 45 seconds
SCRIPT_DIR="$(dirname "$0")"
ARGOCD_WAIT_TIMEOUT=900  # Increased from 600 to 900 seconds (15 minutes)
ARGOCD_CHECK_INTERVAL=30 # 30 seconds

# Cluster configuration using environment variables
CLUSTER_NAMES=(
    "${HUB_CLUSTER_NAME}"
    "${SPOKE_CLUSTER_NAME_PREFIX}-dev"
    "${SPOKE_CLUSTER_NAME_PREFIX}-prod"
)

# Define scripts to run in order
SCRIPTS=(
    "1-argocd-gitlab-setup.sh"
    "2-bootstrap-accounts.sh"
    "3-register-terraform-spoke-clusters.sh dev"
    "3-register-terraform-spoke-clusters.sh prod"
    "4-argocd-bootstrap.sh"
    "6-tools-urls.sh"
)

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    case $status in
        "INFO")
            echo -e "${BLUE}[INFO]${NC} $message"
            ;;
        "SUCCESS")
            echo -e "${GREEN}[SUCCESS]${NC} $message"
            ;;
        "ERROR")
            echo -e "${RED}[ERROR]${NC} $message"
            ;;
        "WARN")
            echo -e "${YELLOW}[WARN]${NC} $message"
            ;;
    esac
}

# Function to wait for EKS clusters to be ready
wait_for_clusters_ready() {
    print_status "INFO" "Checking EKS cluster readiness..."
    
    print_status "INFO" "Using cluster names: ${CLUSTER_NAMES[*]}"
    
    local all_ready=false
    local max_wait=1800  # 30 minutes total wait time
    local check_interval=30
    local start_time=$(date +%s)
    
    while [ $(date +%s) -lt $((start_time + max_wait)) ]; do
        # Check all clusters in parallel
        local temp_dir=$(mktemp -d)
        local pids=()
        
        for i in "${!CLUSTER_NAMES[@]}"; do
            local cluster="${CLUSTER_NAMES[$i]}"
            [ -z "$cluster" ] && continue
            
            (
                local status=$(aws eks describe-cluster --name "$cluster" --region "${AWS_DEFAULT_REGION:-us-east-1}" --query 'cluster.status' --output text 2>/dev/null || echo "NOT_FOUND")
                echo "$cluster:$status" > "$temp_dir/cluster_$i.status"
            ) &
            pids+=($!)
        done
        
        # Wait for all checks
        for pid in "${pids[@]}"; do
            wait "$pid"
        done
        
        # Process results
        all_ready=true
        local ready_count=0
        local total_count=0
        
        for i in "${!CLUSTER_NAMES[@]}"; do
            local cluster="${CLUSTER_NAMES[$i]}"
            [ -z "$cluster" ] && continue
            
            total_count=$((total_count + 1))
            local result=$(cat "$temp_dir/cluster_$i.status" 2>/dev/null || echo "ERROR")
            local status=$(echo "$result" | cut -d: -f2)
            
            case "$status" in
                "ACTIVE")
                    print_status "SUCCESS" "Cluster $cluster is ACTIVE"
                    ready_count=$((ready_count + 1))
                    ;;
                "CREATING"|"UPDATING")
                    print_status "INFO" "Cluster $cluster is $status, waiting..."
                    all_ready=false
                    ;;
                *)
                    print_status "ERROR" "Cluster $cluster status: $status"
                    all_ready=false
                    ;;
            esac
        done
        
        rm -rf "$temp_dir"
        
        # Break out if all clusters are ready
        if [ "$all_ready" = true ]; then
            break
        fi
        
        local remaining_time=$((end_time - $(date +%s)))
        print_status "INFO" "Waiting ${check_interval}s before next check (${remaining_time}s remaining)..."
        sleep $check_interval
    done
    
    if [ "$all_ready" = true ]; then
        print_status "SUCCESS" "All EKS clusters are ready!"
        
        # Update kubeconfig for all clusters
        print_status "INFO" "Updating kubeconfig for all clusters..."
        for cluster in "${CLUSTER_NAMES[@]}"; do
            if [ -n "$cluster" ]; then
                print_status "INFO" "Updating kubeconfig for $cluster"
                if aws eks update-kubeconfig --region "${AWS_DEFAULT_REGION:-us-east-1}" --name "$cluster" --alias "$cluster"; then
                    print_status "SUCCESS" "Kubeconfig updated for $cluster"
                else
                    print_status "ERROR" "Failed to update kubeconfig for $cluster"
                    return 1
                fi
            fi
        done
        
        return 0
    else
        print_status "ERROR" "Timeout waiting for clusters to be ready"
        return 1
    fi
}

# Function to wait for ArgoCD applications to be healthy
wait_for_argocd_health() {
    local timeout=$1
    local start_time=$(date +%s)
    local end_time=$((start_time + timeout))
    local consecutive_failures=0
    local max_consecutive_failures=3
    
    print_status "INFO" "Waiting for ArgoCD applications to be healthy (timeout: ${timeout}s)"
    
    while [ $(date +%s) -lt $end_time ]; do
        # Check if kubectl is available and cluster is accessible
        if ! kubectl get applications -n argocd >/dev/null 2>&1; then
            ((consecutive_failures++))
            if [ $consecutive_failures -ge $max_consecutive_failures ]; then
                print_status "ERROR" "ArgoCD not accessible after multiple attempts"
                return 1
            fi
            print_status "WARN" "ArgoCD not yet accessible, waiting... (failure $consecutive_failures/$max_consecutive_failures)"
            sleep $ARGOCD_CHECK_INTERVAL
            continue
        fi
        
        # Reset failure counter on successful connection
        consecutive_failures=0
        
        # Get application status with error handling
        local app_status
        if ! app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null); then
            print_status "WARN" "Failed to get application status, retrying..."
            sleep 10
            continue
        fi
        
        # Count applications
        local total_apps=$(echo "$app_status" | grep -v '^$' | wc -l)
        if [ "$total_apps" -eq 0 ]; then
            print_status "INFO" "No ArgoCD applications found yet, waiting..."
            sleep $ARGOCD_CHECK_INTERVAL
            continue
        fi
        
        # Count healthy and synced applications
        local healthy_synced_apps=$(echo "$app_status" | awk '$2 == "Healthy" && $3 == "Synced" {count++} END {print count+0}')
        local unhealthy_apps=$(echo "$app_status" | awk '$2 != "Healthy" || $3 == "OutOfSync" {print $1}')
        local unhealthy_count=$(echo "$unhealthy_apps" | grep -v '^$' | wc -l)
        
        # Check if we have acceptable health (allow some apps to be OutOfSync but Healthy)
        local healthy_apps=$(echo "$app_status" | awk '$2 == "Healthy" {count++} END {print count+0}')
        local critical_unhealthy=$(echo "$app_status" | awk '$2 != "Healthy" && $2 != "" {print $1}' | grep -v '^$' | wc -l)
        
        if [ "$critical_unhealthy" -eq 0 ] && [ "$total_apps" -gt 0 ]; then
            print_status "SUCCESS" "All $total_apps ArgoCD applications are healthy ($healthy_synced_apps fully synced)"
            return 0
        fi
        
        # Show current status
        print_status "INFO" "ArgoCD status: $healthy_apps/$total_apps healthy, $healthy_synced_apps/$total_apps synced"
        
        # Show problematic applications (limit output)
        if [ "$unhealthy_count" -gt 0 ]; then
            local current_time=$(date +%s)
            local elapsed=$((current_time - start_time))
            
            # Process unhealthy apps and collect stuck ones
            while read app; do
                if [ -n "$app" ]; then
                    local app_health=$(echo "$app_status" | grep "^$app " | awk '{print $2}')
                    local app_sync=$(echo "$app_status" | grep "^$app " | awk '{print $3}')
                    print_status "INFO" "  ⚠️  $app: $app_health/$app_sync"
                    
                    # Check if app has been stuck for too long (Progressing/OutOfSync)
                    if [ "$app_health" = "Progressing" ] && [ "$app_sync" = "OutOfSync" ]; then
                        print_status "INFO" "DEBUG: Found stuck app $app, elapsed time: ${elapsed}s"
                        if [ $elapsed -gt 30 ]; then  # Reduced to 30 seconds for faster response
                            print_status "INFO" "Force syncing stuck application: $app (stuck for ${elapsed}s)"
                            argocd app terminate-op "$app" 2>/dev/null || true
                            sleep 2
                            argocd app sync "$app" --timeout 60 2>/dev/null || {
                                print_status "INFO" "ArgoCD CLI failed, using kubectl patch for $app"
                                kubectl patch application "$app" -n argocd --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
                            }
                        fi
                    fi
                fi
            done <<< "$(echo "$unhealthy_apps" | head -5)"
            
            if [ "$unhealthy_count" -gt 5 ]; then
                print_status "INFO" "  ... and $((unhealthy_count - 5)) more"
            fi
        fi
        
        sleep $ARGOCD_CHECK_INTERVAL
    done
    
    print_status "WARN" "Timeout waiting for ArgoCD applications to be fully healthy"
    return 1
}

# Function to sync and wait for specific ArgoCD application
sync_and_wait_app() {
    local app_name=$1
    local max_wait=${2:-300}  # 5 minutes default
    
    print_status "INFO" "Syncing ArgoCD application: $app_name"
    
    # Check if application exists first
    if ! kubectl get application "$app_name" -n argocd >/dev/null 2>&1; then
        print_status "WARN" "Application $app_name not found, skipping sync"
        return 1
    fi
    
    # Try to sync the application
    if command -v argocd >/dev/null 2>&1; then
        print_status "INFO" "Using ArgoCD CLI to sync $app_name"
        argocd app sync "$app_name" --timeout 60 2>/dev/null || {
            print_status "WARN" "ArgoCD CLI sync failed for $app_name, trying kubectl patch"
            kubectl patch application "$app_name" -n argocd --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
        }
    else
        print_status "INFO" "Using kubectl to trigger sync for $app_name"
        kubectl patch application "$app_name" -n argocd --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}' 2>/dev/null || {
            print_status "WARN" "Failed to trigger sync for $app_name"
        }
    fi
    
    # Wait for the application to be healthy
    local start_time=$(date +%s)
    local end_time=$((start_time + max_wait))
    local last_status=""
    
    while [ $(date +%s) -lt $end_time ]; do
        local health=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null || echo "Unknown")
        local sync=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "Unknown")
        local current_status="$health/$sync"
        
        if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ]; then
            print_status "SUCCESS" "Application $app_name is healthy and synced"
            return 0
        fi
        
        # Only print status if it changed to reduce noise
        if [ "$current_status" != "$last_status" ]; then
            print_status "INFO" "Waiting for $app_name: $current_status"
            last_status="$current_status"
        fi
        
        # If app is healthy but not synced, that's often acceptable
        if [ "$health" = "Healthy" ] && [ "$sync" = "OutOfSync" ]; then
            local remaining_time=$((end_time - $(date +%s)))
            if [ $remaining_time -lt 60 ]; then
                print_status "SUCCESS" "Application $app_name is healthy (OutOfSync acceptable)"
                return 0
            fi
        fi
        
        sleep 10
    done
    
    print_status "WARN" "Application $app_name did not become fully synced within ${max_wait}s (final status: $last_status)"
    return 1
}

# Function to run script with retry logic
run_script_with_retry() {
    local script_path=$1
    shift  # Remove script_path from arguments
    local script_args="$*"  # Remaining arguments
    local script_name=$(basename "$script_path")
    local attempt=1
    
    print_status "INFO" "Starting execution of $script_name $script_args"
    
    while [ $attempt -le $MAX_RETRIES ]; do
        print_status "INFO" "Attempt $attempt/$MAX_RETRIES for $script_name"
        
        if [ -n "$script_args" ]; then
            bash "$script_path" $script_args
        else
            bash "$script_path"
        fi
        local exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
            print_status "SUCCESS" "$script_name completed successfully"
            
            # Special handling for ArgoCD setup script
            if [[ "$script_name" == "1-argocd-gitlab-setup.sh" ]]; then
                print_status "INFO" "Performing post-ArgoCD setup validation..."
                
                # Wait for ArgoCD to be accessible
                local argocd_ready=false
                for i in {1..10}; do
                    if kubectl get deployment argocd-repo-server -n argocd >/dev/null 2>&1; then
                        argocd_ready=true
                        break
                    fi
                    print_status "INFO" "Waiting for ArgoCD to be accessible (attempt $i/10)..."
                    sleep 15
                done
                
                if [ "$argocd_ready" = false ]; then
                    print_status "ERROR" "ArgoCD is not accessible after setup"
                    return 1
                fi
                
                # Check ArgoCD repo server health
                print_status "INFO" "Verifying ArgoCD repo server health..."
                if ! kubectl rollout status deployment argocd-repo-server -n argocd --timeout=120s; then
                    print_status "WARN" "ArgoCD repo server rollout status check failed, but continuing..."
                fi
                
                # Try to sync critical applications with error handling
                print_status "INFO" "Checking critical ArgoCD applications status..."
                # Skip bootstrap sync since 1-argocd-gitlab-setup.sh already synced it
                # sync_and_wait_app "bootstrap" 180 || print_status "WARN" "Bootstrap app sync had issues, continuing..."
                
                # Brief wait for stabilization
                sleep 30
                
                # Check overall ArgoCD health with shorter timeout
                if wait_for_argocd_health 300; then
                    print_status "SUCCESS" "ArgoCD platform is operational"
                else
                    print_status "WARN" "Some ArgoCD applications may still be syncing"
                    # Show current status for debugging
                    kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status" --no-headers 2>/dev/null | head -10
                fi
            fi
            
            return 0
        else
            local exit_code=$?
            print_status "ERROR" "$script_name failed with exit code $exit_code (attempt $attempt/$MAX_RETRIES)"
            
            # Special recovery for ArgoCD setup failures
            if [[ "$script_name" == "1-argocd-gitlab-setup.sh" ]] && [ $attempt -lt $MAX_RETRIES ]; then
                print_status "INFO" "Attempting ArgoCD recovery before retry..."
                
                # Check if ArgoCD namespace exists and clean up if needed
                if kubectl get namespace argocd >/dev/null 2>&1; then
                    print_status "INFO" "Checking ArgoCD deployment status..."
                    kubectl get deployments -n argocd || true
                    
                    # Terminate stuck ArgoCD operations (running > 3 minutes)
                    print_status "INFO" "Checking for stuck ArgoCD operations..."
                    local stuck_apps=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.operationState.phase}{" "}{.status.operationState.startedAt}{"\n"}{end}' 2>/dev/null | \
                        awk -v now=$(date +%s) '$2=="Running" && (now - mktime(gensub(/[-T:Z]/, " ", "g", $3))) > 180 {print $1}')
                    
                    if [ -n "$stuck_apps" ]; then
                        echo "$stuck_apps" | while read -r app; do
                            print_status "WARN" "Terminating stuck operation for $app"
                            kubectl patch application "$app" -n argocd --type merge -p '{"operation":null}' 2>/dev/null || true
                        done
                    fi
                    
                    # Force restart ArgoCD components if they exist
                    kubectl rollout restart deployment argocd-server -n argocd 2>/dev/null || true
                    kubectl rollout restart deployment argocd-repo-server -n argocd 2>/dev/null || true
                    
                    # Clean up any stuck pods
                    kubectl delete pods -n argocd --field-selector=status.phase=Failed 2>/dev/null || true
                fi
                
                sleep 30
            fi
            
            if [ $attempt -lt $MAX_RETRIES ]; then
                print_status "WARN" "Retrying $script_name in $RETRY_DELAY seconds..."
                sleep $RETRY_DELAY
            else
                print_status "ERROR" "$script_name failed after $MAX_RETRIES attempts"
                return $exit_code
            fi
        fi
        
        ((attempt++))
    done
}

# Function to show final status
show_final_status() {
    print_status "INFO" "Final ArgoCD Applications Status:"
    echo "----------------------------------------"
    
    if kubectl get applications -n argocd >/dev/null 2>&1; then
        kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status" --no-headers | \
        while read name sync health; do
            if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ]; then
                echo -e "  ${GREEN}✓${NC} $name: $sync/$health"
            elif [ "$health" = "Healthy" ]; then
                echo -e "  ${YELLOW}⚠${NC} $name: $sync/$health"
            else
                echo -e "  ${RED}✗${NC} $name: $sync/$health"
            fi
        done
    else
        print_status "ERROR" "Cannot access ArgoCD applications"
    fi
    
    echo "----------------------------------------"
}

# Main execution
main() {
    print_status "INFO" "Starting bootstrap deployment process"
    print_status "INFO" "Script directory: $SCRIPT_DIR"
    print_status "INFO" "Max retries per script: $MAX_RETRIES"
    print_status "INFO" "Retry delay: $RETRY_DELAY seconds"
    print_status "INFO" "ArgoCD wait timeout: $ARGOCD_WAIT_TIMEOUT seconds"
    print_status "INFO" "Scripts to execute: ${SCRIPTS[*]}"
    
    # Wait for all EKS clusters to be ready before proceeding
    if ! wait_for_clusters_ready; then
        print_status "ERROR" "EKS clusters are not ready. Aborting bootstrap process."
        exit 1
    fi
    
    for script_entry in "${SCRIPTS[@]}"; do
        # Parse script name and arguments
        local script_name=$(echo "$script_entry" | cut -d' ' -f1)
        local script_args=$(echo "$script_entry" | cut -d' ' -f2-)
        
        # If no args, script_args will equal script_name
        if [ "$script_args" = "$script_name" ]; then
            script_args=""
        fi
        
        local script_path="$SCRIPT_DIR/$script_name"
        
        print_status "INFO" "Preparing to run: $script_name $script_args"
        
        if [ ! -f "$script_path" ]; then
            print_status "ERROR" "Script not found: $script_path"
            exit 1
        fi
        
        if [ ! -x "$script_path" ]; then
            print_status "ERROR" "Script not executable: $script_path"
            exit 1
        fi
        
        # Run script with retry logic
        if ! run_script_with_retry "$script_path" $script_args; then
            print_status "ERROR" "Bootstrap process failed at script: $script_name"
            show_final_status
            exit 1
        fi
        
        print_status "SUCCESS" "Script $script_name completed successfully"
        echo "----------------------------------------"
    done
    
    print_status "SUCCESS" "Bootstrap deployment process completed successfully!"
    print_status "INFO" "All scripts have been executed successfully:"
    for script_name in "${SCRIPTS[@]}"; do
        print_status "INFO" "  ✓ $script_name"
    done
    
    # Show final status
    show_final_status
}

# Trap to handle script interruption
trap 'print_status "ERROR" "Bootstrap process interrupted"; show_final_status; exit 130' INT TERM

# Run main function
main "$@"
