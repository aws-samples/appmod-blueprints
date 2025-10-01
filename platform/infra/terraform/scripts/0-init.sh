#!/bin/bash

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

# Debug: Show platform.sh contents at script start
echo "=== DEBUG: Contents of /home/ec2-user/.bashrc.d/platform.sh at script start ==="
if [ -f "/home/ec2-user/.bashrc.d/platform.sh" ]; then
    cat /home/ec2-user/.bashrc.d/platform.sh
else
    echo "ERROR: /home/ec2-user/.bashrc.d/platform.sh does not exist!"
fi
echo "=== END DEBUG ==="

GIT_ROOT_PATH=$(git rev-parse --show-toplevel)

# Source utils.sh
source "${GIT_ROOT_PATH}/platform/infra/terraform/scripts/utils.sh"

# Configuration
SCRIPT_DIR="$(dirname "$0")"
WAIT_TIMEOUT=1800  #(30 minutes)
CHECK_INTERVAL=30 # 30 seconds


# Main execution
main() {
    print_status "INFO" "Starting bootstrap deployment process"
    print_status "INFO" "Script directory: $SCRIPT_DIR"
    print_status "INFO" "ArgoCD re-check interval: $CHECK_INTERVAL seconds"
    print_status "INFO" "ArgoCD apps wait timeout: $WAIT_TIMEOUT seconds"
    
    for cluster in "${CLUSTER_NAMES[@]}"; do
        configure_kubectl_with_fallback "$cluster"
    done

    #TODO: Switch the kubeconfig context to the hub cluster, first cluster is assumed as Hub cluster
    if ! kubectl config use-context "${CLUSTER_NAMES[0]}"; then
        print_status "ERROR" "Failed to switch kubeconfig context to ${CLUSTER_NAMES[0]}"
        exit 1
    fi

    source "$SCRIPT_DIR/backstage-utils.sh"

    if ! check_backstage_ecr_repo; then
        # Start Backstage Build Process
        start_backstage_build
    fi

    # Wait for Argo CD apps to be healthy
    if ! wait_for_argocd_apps_health; then 
        print_status "ERROR" "ArgoCD apps did not become healthy within the timeout"
        show_final_status
        exit 1
    fi
    
    # Wait for Backstage build to complete with timeout if it has started
    if [[ -n $BACKSTAGE_BUILD_PID ]]; then
        print_status "INFO" "Waiting for Backstage build to complete..."
        local elapsed=0
        local check_interval=$CHECK_INTERVAL
        while check_backstage_build_status; do
            if [ $elapsed -ge $WAIT_TIMEOUT ]; then
                print_status "ERROR" "Backstage build timed out after ${WAIT_TIMEOUT}s"
                return 1
            fi
            print_status "INFO" "Backstage build still running... (${elapsed}s elapsed)"
            sleep $check_interval
            elapsed=$((elapsed + check_interval))
        done
        
        print_status "SUCCESS" "Backstage build completed"
    fi

    print_status "SUCCESS" "Bootstrap deployment process completed successfully!"

    # Show final status
    show_final_status

    # Set up Secrets and URLs for workshop.
    bash "$SCRIPT_DIR/1-tools-urls.sh"
}

# Trap to handle script interruption
trap 'print_status "ERROR" "Bootstrap process interrupted"; show_final_status; exit 130' INT TERM

# Run main function
main "$@"
