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

    if ! check_backstage_ecr_image; then
        # Start Backstage Build Process
        start_backstage_build
        # Ensure BACKSTAGE_BUILD_PID is available in this scope
        export BACKSTAGE_BUILD_PID
    fi

    # Wait for Argo CD apps to be healthy
    if ! wait_for_argocd_apps_health; then 
        print_status "ERROR" "ArgoCD apps did not become healthy within the timeout"
        show_final_status
        exit 1
    fi


    # Initialize GitLab configuration
    bash "$SCRIPT_DIR/2-gitlab-init.sh"

    # Set up Secrets and URLs for workshop.
    bash "$SCRIPT_DIR/1-tools-urls.sh"
    
    # Wait for Backstage build to complete if it has started
    if [[ -n $BACKSTAGE_BUILD_PID ]]; then
        print_status "INFO" "Waiting for Backstage build to complete..."
        
        # Check if the process is still running
        if kill -0 $BACKSTAGE_BUILD_PID 2>/dev/null; then
            print_status "INFO" "Backstage build is still running, waiting for completion..."
            if wait $BACKSTAGE_BUILD_PID; then
                print_status "SUCCESS" "Backstage image build completed successfully"
            else
                print_status "ERROR" "Backstage image build failed"
                if [ -f "$BACKSTAGE_LOG" ]; then
                    print_status "ERROR" "Build log (last 20 lines):"
                    tail -n 20 "$BACKSTAGE_LOG" | sed 's/^/  /'
                fi
                exit 1
            fi
        else
            # Process already finished, check exit status
            if wait $BACKSTAGE_BUILD_PID 2>/dev/null; then
                print_status "SUCCESS" "Backstage image build already completed successfully"
            else
                print_status "ERROR" "Backstage image build failed"
                if [ -f "$BACKSTAGE_LOG" ]; then
                    print_status "ERROR" "Build log (last 20 lines):"
                    tail -n 20 "$BACKSTAGE_LOG" | sed 's/^/  /'
                fi
                exit 1
            fi
        fi
    fi

    print_status "SUCCESS" "Bootstrap deployment process completed successfully!"

    # Show final status
    show_final_status

}

# Trap to handle script interruption
trap 'print_status "ERROR" "Bootstrap process interrupted"; show_final_status; exit 130' INT TERM

# Run main function
main "$@"
