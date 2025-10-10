#!/bin/bash

#be sure we source env var
source /etc/profile.d/workshop.sh

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

    source "$SCRIPT_DIR/backstage-utils.sh"

    if ! check_backstage_ecr_image; then
        # Start Backstage Build Process
        start_backstage_build
        # Ensure BACKSTAGE_BUILD_PID is available in this scope
        export BACKSTAGE_BUILD_PID
    fi

    # Wait for Argo CD apps to be healthy with retry mechanism
    local retry_count=0
    local max_retries=5
    
    while [ $retry_count -lt $max_retries ]; do
        print_status "INFO" "Attempt $((retry_count + 1))/$max_retries: Waiting for ArgoCD apps to be healthy..."
        
        # Handle OutOfSync/Missing apps specifically before health check
        local missing_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | jq -r '.items[] | select(.status.sync.status == "OutOfSync" and .status.health.status == "Missing") | .metadata.name' 2>/dev/null || echo "")
        if [ -n "$missing_apps" ]; then
            print_status "INFO" "Found OutOfSync/Missing apps, forcing refresh and sync..."
            echo "$missing_apps" | while read -r app; do
                if [ -n "$app" ]; then
                    print_status "INFO" "Aggressively fixing $app..."
                    # More aggressive approach
                    kubectl patch application.argoproj.io "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
                    kubectl patch application.argoproj.io "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/status"}]' 2>/dev/null || true
                    sleep 3
                    kubectl annotate application.argoproj.io "$app" -n argocd argocd.argoproj.io/refresh="hard" --overwrite 2>/dev/null || true
                    sleep 5
                    kubectl patch application.argoproj.io "$app" -n argocd --type='merge' -p='{"operation":{"sync":{"revision":"HEAD","prune":true}}}' 2>/dev/null || true
                    sleep 10
                fi
            done
        fi
        
        if wait_for_argocd_apps_health; then
            # Double-check no OutOfSync/Missing apps remain
            local remaining_missing=$(kubectl get applications -n argocd -o json 2>/dev/null | jq -r '.items[] | select(.status.sync.status == "OutOfSync" and .status.health.status == "Missing") | .metadata.name' 2>/dev/null || echo "")
            if [ -n "$remaining_missing" ]; then
                print_status "WARNING" "Still have OutOfSync/Missing apps: $remaining_missing"
                retry_count=$((retry_count + 1))
                continue
            fi
            print_status "SUCCESS" "ArgoCD apps are healthy"
            break
        else
            retry_count=$((retry_count + 1))
            if [ $retry_count -lt $max_retries ]; then
                print_status "WARNING" "ArgoCD apps not healthy yet, retrying in 60 seconds..."
                force_sync_all_apps
                sleep 60
            else
                print_status "ERROR" "ArgoCD apps did not become healthy after $max_retries attempts"
                show_final_status
                print_status "WARNING" "Continuing with deployment despite ArgoCD app health issues..."
                break
            fi
        fi
    done


    # Initialize GitLab configuration
    bash "$SCRIPT_DIR/2-gitlab-init.sh"
    
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

    # Set up Secrets and URLs for workshop.
    bash "$SCRIPT_DIR/1-tools-urls.sh"
    
    # Show final status
    show_final_status

}

# Trap to handle script interruption
trap 'print_status "ERROR" "Bootstrap process interrupted"; show_final_status; exit 130' INT TERM

# Run main function
main "$@"
