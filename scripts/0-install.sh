#!/bin/bash

# Bootstrap script to run deployment scripts in order with retry logic
# Runs: 1-argocd-gitlab-setup.sh, 2-bootstrap-accounts.sh, and 6-tools-urls.sh in sequence
# Each script must succeed before proceeding to the next

set -e

# Source all environment files in .bashrc.d
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.bash; do
        if [ -f "$file" ]; then
            source "$file"
        fi
    done
fi

# Source colors for output formatting
source "$(dirname "$0")/colors.sh"

# Configuration
MAX_RETRIES=3
RETRY_DELAY=30
SCRIPT_DIR="$(dirname "$0")"
ARGOCD_WAIT_TIMEOUT=600  # 10 minutes
ARGOCD_CHECK_INTERVAL=30 # 30 seconds

# Define scripts to run in order
SCRIPTS=(
    "1-argocd-gitlab-setup.sh"
    "2-bootstrap-accounts.sh"
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

# Function to wait for ArgoCD applications to be healthy
wait_for_argocd_health() {
    local timeout=$1
    local start_time=$(date +%s)
    local end_time=$((start_time + timeout))
    
    print_status "INFO" "Waiting for ArgoCD applications to be healthy (timeout: ${timeout}s)"
    
    while [ $(date +%s) -lt $end_time ]; do
        # Check if kubectl is available and cluster is accessible
        if ! kubectl get applications -n argocd >/dev/null 2>&1; then
            print_status "WARN" "ArgoCD not yet accessible, waiting..."
            sleep $ARGOCD_CHECK_INTERVAL
            continue
        fi
        
        # Get application status
        local unhealthy_apps=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null | \
            awk '$2 != "Healthy" || $3 == "OutOfSync" {print $1}' | wc -l)
        
        local total_apps=$(kubectl get applications -n argocd --no-headers 2>/dev/null | wc -l)
        
        if [ "$unhealthy_apps" -eq 0 ] && [ "$total_apps" -gt 0 ]; then
            print_status "SUCCESS" "All $total_apps ArgoCD applications are healthy and synced"
            return 0
        fi
        
        # Show current status
        local healthy_apps=$((total_apps - unhealthy_apps))
        print_status "INFO" "ArgoCD status: $healthy_apps/$total_apps applications healthy"
        
        # Show problematic applications
        kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null | \
            awk '$2 != "Healthy" || $3 == "OutOfSync" {print "  ⚠️  " $1 ": " $2 "/" $3}'
        
        sleep $ARGOCD_CHECK_INTERVAL
    done
    
    print_status "ERROR" "Timeout waiting for ArgoCD applications to be healthy"
    return 1
}

# Function to sync and wait for specific ArgoCD application
sync_and_wait_app() {
    local app_name=$1
    local max_wait=${2:-300}  # 5 minutes default
    
    print_status "INFO" "Syncing ArgoCD application: $app_name"
    
    # Try to sync the application
    if command -v argocd >/dev/null 2>&1; then
        argocd app sync "$app_name" --timeout 60 2>/dev/null || true
    else
        kubectl patch application "$app_name" -n argocd --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
    fi
    
    # Wait for the application to be healthy
    local start_time=$(date +%s)
    local end_time=$((start_time + max_wait))
    
    while [ $(date +%s) -lt $end_time ]; do
        local health=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null || echo "Unknown")
        local sync=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "Unknown")
        
        if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ]; then
            print_status "SUCCESS" "Application $app_name is healthy and synced"
            return 0
        fi
        
        print_status "INFO" "Waiting for $app_name: $health/$sync"
        sleep 10
    done
    
    print_status "WARN" "Application $app_name did not become healthy within ${max_wait}s"
    return 1
}

# Function to run script with retry logic
run_script_with_retry() {
    local script_path=$1
    local script_name=$(basename "$script_path")
    local attempt=1
    
    print_status "INFO" "Starting execution of $script_name"
    
    while [ $attempt -le $MAX_RETRIES ]; do
        print_status "INFO" "Attempt $attempt/$MAX_RETRIES for $script_name"
        
        if bash "$script_path"; then
            print_status "SUCCESS" "$script_name completed successfully"
            
            # Special handling for ArgoCD setup script
            if [[ "$script_name" == "1-argocd-gitlab-setup.sh" ]]; then
                print_status "INFO" "Waiting for ArgoCD applications to stabilize..."
                
                # Wait a bit for initial deployment
                sleep 30
                
                # Try to sync critical applications
                sync_and_wait_app "bootstrap" 300
                sync_and_wait_app "cluster-addons" 300
                
                # Wait for overall health
                if wait_for_argocd_health $ARGOCD_WAIT_TIMEOUT; then
                    print_status "SUCCESS" "ArgoCD platform is fully operational"
                else
                    print_status "WARN" "Some ArgoCD applications may still be syncing, but continuing..."
                fi
            fi
            
            return 0
        else
            local exit_code=$?
            print_status "ERROR" "$script_name failed with exit code $exit_code (attempt $attempt/$MAX_RETRIES)"
            
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
    
    for script_name in "${SCRIPTS[@]}"; do
        local script_path="$SCRIPT_DIR/$script_name"
        
        print_status "INFO" "Preparing to run: $script_name"
        
        if [ ! -f "$script_path" ]; then
            print_status "ERROR" "Script not found: $script_path"
            exit 1
        fi
        
        if [ ! -x "$script_path" ]; then
            print_status "ERROR" "Script not executable: $script_path"
            exit 1
        fi
        
        # Run script with retry logic
        if ! run_script_with_retry "$script_path"; then
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
