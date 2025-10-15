#!/bin/bash

#be sure we source env var
source /etc/profile.d/workshop.sh

# Debug: Show platform.sh contents at script start
echo "=== DEBUG: Contents of /home/ec2-user/.bashrc.d/platform.sh at script start ==="
if [ -f "/home/ec2-user/.bashrc.d/platform.sh" ]; then
    cat /home/ec2-user/.bashrc.d/platform.sh
    source /home/ec2-user/.bashrc.d/platform.sh
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

    # Wait for ArgoCD to be fully ready first
    print_status "INFO" "Waiting for ArgoCD to be fully ready..."
    local argocd_ready=false
    local argocd_wait_time=0
    local argocd_max_wait=900  # 15 minutes
    
    while [ $argocd_wait_time -lt $argocd_max_wait ] && [ "$argocd_ready" = false ]; do
        # Check if ArgoCD deployments are ready
        local argocd_pods_ready=$(kubectl get deployment -n argocd argocd-server -o jsonpath='{.status.readyReplicas}' 2>/dev/null | head -1 || echo "0")
        local argocd_repo_ready=$(kubectl get deployment -n argocd argocd-repo-server -o jsonpath='{.status.readyReplicas}' 2>/dev/null | head -1 || echo "0")
        
        # Check if ArgoCD API is responding
        local api_ready=false
        if kubectl get applications -n argocd >/dev/null 2>&1; then
            api_ready=true
        fi
        
        # Check if ArgoCD domain is available (this was the missing piece!)
        local domain_available=false
        local domain_name=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null)
        if [ -z "$domain_name" ] || [ "$domain_name" = "null" ]; then
            domain_name=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text 2>/dev/null)
        fi
        
        if [ -n "$domain_name" ] && [ "$domain_name" != "None" ] && [ "$domain_name" != "null" ]; then
            domain_available=true
            print_status "INFO" "ArgoCD domain found: $domain_name"
        fi
        
        if [ "$argocd_pods_ready" -gt 0 ] && [ "$argocd_repo_ready" -gt 0 ] && [ "$api_ready" = true ] && [ "$domain_available" = true ]; then
            print_status "SUCCESS" "ArgoCD is ready (server: $argocd_pods_ready, repo: $argocd_repo_ready, api: responding, domain: $domain_name)"
            argocd_ready=true
        else
            print_status "INFO" "ArgoCD not ready yet (server: $argocd_pods_ready, repo: $argocd_repo_ready, api: $api_ready, domain: $domain_available), waiting..."
            sleep 30
            argocd_wait_time=$((argocd_wait_time + 30))
        fi
    done
    
    if [ "$argocd_ready" = false ]; then
        print_status "ERROR" "ArgoCD did not become ready within $argocd_max_wait seconds"
        exit 1
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
            print_status "INFO" "Missing apps list: $missing_apps"
            
            # Process all apps concurrently
            local pids=()
            echo "$missing_apps" | while read -r app; do
                if [ -n "$app" ]; then
                    {
                        print_status "INFO" "[$app] TERMINATE-OP: Using terminate_argocd_operation"
                        terminate_argocd_operation "$app"
                        sleep 5
                        
                        print_status "INFO" "[$app] REFRESH: Using refresh_argocd_app with hard refresh"
                        refresh_argocd_app "$app" "true"
                        sleep 10
                        
                        print_status "INFO" "[$app] SYNC: Using sync_argocd_app"
                        sync_argocd_app "$app"
                        print_status "INFO" "[$app] Sync operation completed"
                    } &
                    pids+=($!)
                fi
            done
            
            # Wait for all background processes to complete
            print_status "INFO" "Waiting for all sync operations to complete..."
            for pid in "${pids[@]}"; do
                wait "$pid"
            done
            
            # Additional wait after processing all apps to allow Git revision sync
            print_status "INFO" "Waiting for Git revision synchronization..."
            sleep 30
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
