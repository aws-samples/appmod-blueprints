#!/bin/bash

# Enable alias expansion in non-interactive shell
if [[ -n "$ZSH_VERSION" ]]; then
  setopt aliases
else
  shopt -s expand_aliases
fi

# Best effort applications - sync but don't wait for them to be healthy
# These apps may take longer to deploy or have known issues that don't block the workshop
BEST_EFFORT_APPS=(
    "devlake-peeks-hub"
    "grafana-dashboards-peeks-hub"
    "jupyterhub-peeks-hub"
    "spark-operator-peeks-hub"
    "image-prepuller-peeks-hub"
)

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
WAIT_TIMEOUT=${BOOTSTRAP_WAIT_TIMEOUT:-5400}  # 90 minutes (can be overridden via env var)
CHECK_INTERVAL=30 # 30 seconds
MAX_SYNC_RETRIES=3  # Maximum retries for stuck apps

# Export for use in sourced scripts
export WAIT_TIMEOUT
export CHECK_INTERVAL


# Main execution
main() {
    print_status "INFO" "Starting bootstrap deployment process"
    print_status "INFO" "Script directory: $SCRIPT_DIR"
    print_status "INFO" "ArgoCD re-check interval: $CHECK_INTERVAL seconds"
    print_status "INFO" "ArgoCD apps wait timeout: $WAIT_TIMEOUT seconds"

    source "$SCRIPT_DIR/backstage-utils.sh"

    # Ensure clusters are fully ready before proceeding
    print_status "INFO" "Verifying cluster readiness before starting deployment..."
    for cluster_name in "${CLUSTER_NAMES[@]}"; do
        print_status "INFO" "Checking cluster: $cluster_name"
        
        # Switch to cluster context
        if ! kubectl config use-context "$cluster_name" >/dev/null 2>&1; then
            print_status "WARNING" "Could not switch to cluster context $cluster_name, attempting to configure..."
            configure_kubectl_with_fallback "$cluster_name"
        fi
        
        # Wait for cluster to be responsive
        local cluster_ready=false
        local cluster_wait=0
        while [ $cluster_wait -lt 300 ] && [ "$cluster_ready" = false ]; do
            if kubectl get nodes --request-timeout=10s >/dev/null 2>&1; then
                local ready_nodes=$(kubectl get nodes --no-headers 2>/dev/null | grep -c "Ready" || echo "0")
                ready_nodes=$(echo "$ready_nodes" | tr -d '[:space:]-')
                if [ "${ready_nodes:-0}" -gt 0 ] 2>/dev/null; then
                    print_status "SUCCESS" "Cluster $cluster_name is ready with $ready_nodes nodes"
                    cluster_ready=true
                else
                    print_status "INFO" "Cluster $cluster_name has no ready nodes yet, waiting..."
                    sleep 15
                    cluster_wait=$((cluster_wait + 15))
                fi
            else
                print_status "INFO" "Cluster $cluster_name API not responsive yet, waiting..."
                sleep 15
                cluster_wait=$((cluster_wait + 15))
            fi
        done
        
        if [ "$cluster_ready" = false ]; then
            print_status "ERROR" "Cluster $cluster_name did not become ready within 5 minutes"
            exit 1
        fi
    done
    
    # Switch back to hub cluster for ArgoCD operations
    kubectl config use-context "${RESOURCE_PREFIX}-hub" >/dev/null 2>&1

    #We do not build backstage as we are using public ECR
    #uncomment this if you want to build image from local
    #if ! check_backstage_ecr_image; then
    #    # Start Backstage Build Process
    #    start_backstage_build
    #    # Ensure BACKSTAGE_BUILD_PID is available in this scope
    #    export BACKSTAGE_BUILD_PID
    #fi

    # Wait for ArgoCD to be fully ready first (EKS Capabilities version)
    print_status "INFO" "Waiting for ArgoCD EKS capability to be ready..."
    local argocd_ready=false
    local argocd_wait_time=0
    local argocd_max_wait=1800  # 30 minutes (increased from 20)
    
    while [ $argocd_wait_time -lt $argocd_max_wait ] && [ "$argocd_ready" = false ]; do
        # Check if ArgoCD namespace exists first
        if ! kubectl get namespace argocd >/dev/null 2>&1; then
            print_status "INFO" "ArgoCD namespace not found, waiting..."
            sleep 30
            argocd_wait_time=$((argocd_wait_time + 30))
            continue
        fi
        
        # For EKS capabilities, ArgoCD runs as managed service - only check API availability
        if timeout 10 kubectl get applications -n argocd >/dev/null 2>&1; then
            print_status "SUCCESS" "ArgoCD EKS capability is ready (API responding)"
            argocd_ready=true
        else
            print_status "INFO" "ArgoCD EKS capability API not ready yet, waiting... ($argocd_wait_time/$argocd_max_wait seconds)"
            sleep 30
            argocd_wait_time=$((argocd_wait_time + 30))
        fi
    done
    
    if [ "$argocd_ready" = false ]; then
        print_status "WARNING" "ArgoCD did not become fully ready within $argocd_max_wait seconds"
        
        # Check if we have basic ArgoCD functionality
        if kubectl get namespace argocd >/dev/null 2>&1 && kubectl get applications -n argocd >/dev/null 2>&1; then
            print_status "WARNING" "ArgoCD namespace and API are available, continuing with deployment..."
            print_status "INFO" "This may be due to slow CloudFront distribution setup or pod startup times"
        else
            print_status "ERROR" "ArgoCD is not functional, cannot continue"
            exit 1
        fi
    fi

    # Dependency-aware ArgoCD app synchronization
    wait_for_argocd_apps_with_dependencies

    # Get GitLab domain from CloudFront distribution
    if [ -z "$GITLAB_DOMAIN" ]; then
        print_status "INFO" "Retrieving GitLab domain from CloudFront..."
        GITLAB_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, 'gitlab')].DomainName" --output text)
        if [ -z "$GITLAB_DOMAIN" ]; then
            print_status "ERROR" "Failed to retrieve GitLab domain from CloudFront"
            exit 1
        fi
        print_status "SUCCESS" "GitLab domain: $GITLAB_DOMAIN"
        update_workshop_var "GITLAB_DOMAIN" "$GITLAB_DOMAIN"
    fi

    # Setup GitLab remote for local environment
    cd "$GIT_ROOT_PATH"
    git config --global credential.helper store
    git config --global user.name "$GIT_USERNAME"
    git config --global user.email "$GIT_USERNAME@workshop.local"
    
    GITLAB_URL="https://${GIT_USERNAME}:${USER1_PASSWORD}@${GITLAB_DOMAIN}/${GIT_USERNAME}/${WORKING_REPO}.git"
    
    # Preserve GitHub as 'github' remote if origin points to GitHub
    if git remote get-url origin 2>/dev/null | grep -q "github.com"; then
        if ! git remote get-url github >/dev/null 2>&1; then
            git remote rename origin github
        fi
    fi
    
    # Set GitLab as origin
    if git remote get-url origin >/dev/null 2>&1; then
        git remote set-url origin "$GITLAB_URL"
    else
        git remote add origin "$GITLAB_URL"
    fi
    
    # Try to fetch from GitLab, but don't fail if repository doesn't exist yet
    if git fetch origin 2>/dev/null; then
        print_status "INFO" "Fetched from GitLab repository"
        git checkout -B main origin/main 2>/dev/null || git checkout -B main
    else
        print_status "WARNING" "GitLab repository not accessible yet, will be initialized by 2-gitlab-init.sh"
        git checkout -B main 2>/dev/null || true
    fi
    cd -

    # Initialize GitLab configuration
    bash "$SCRIPT_DIR/2-gitlab-init.sh"
    
    # Wait for Backstage build to complete if it has started
    # Uncomment this if you want to build backstage locally
    # if [[ -n $BACKSTAGE_BUILD_PID ]]; then
    #     print_status "INFO" "Waiting for Backstage build to complete..."
        
    #     # Check if the process is still running
    #     if kill -0 $BACKSTAGE_BUILD_PID 2>/dev/null; then
    #         print_status "INFO" "Backstage build is still running, waiting for completion..."
    #         if wait $BACKSTAGE_BUILD_PID; then
    #             print_status "SUCCESS" "Backstage image build completed successfully"
    #         else
    #             print_status "ERROR" "Backstage image build failed"
    #             if [ -f "$BACKSTAGE_LOG" ]; then
    #                 print_status "ERROR" "Build log (last 20 lines):"
    #                 tail -n 20 "$BACKSTAGE_LOG" | sed 's/^/  /'
    #             fi
    #             exit 1
    #         fi
    #     else
    #         # Process already finished, check exit status
    #         if wait $BACKSTAGE_BUILD_PID 2>/dev/null; then
    #             print_status "SUCCESS" "Backstage image build already completed successfully"
    #         else
    #             print_status "ERROR" "Backstage image build failed"
    #             if [ -f "$BACKSTAGE_LOG" ]; then
    #                 print_status "ERROR" "Build log (last 20 lines):"
    #                 tail -n 20 "$BACKSTAGE_LOG" | sed 's/^/  /'
    #             fi
    #             exit 1
    #         fi
    #     fi
    # fi
    # print_status "SUCCESS" "Bootstrap deployment process completed successfully!"

    # Set up Secrets and URLs for workshop.
    bash "$SCRIPT_DIR/1-tools-urls.sh"
    
    # Show final status
    show_final_status
    
    # Validate workshop setup and recover any issues
    print_status "INFO" "Running final workshop validation..."
    if bash "$SCRIPT_DIR/check-workshop-setup.sh"; then
        print_status "SUCCESS" "Workshop setup validation completed - all components healthy!"
    else
        print_status "WARNING" "Workshop setup validation found issues - check output above"
        print_status "INFO" "You can run 'check-workshop-setup' command later to verify"
    fi

}

# Trap to handle script interruption
trap 'print_status "ERROR" "Bootstrap process interrupted"; show_final_status; exit 130' INT TERM

# Run main function
main "$@"
