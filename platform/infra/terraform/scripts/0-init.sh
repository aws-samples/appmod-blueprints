#!/bin/bash

# Enable alias expansion in non-interactive shell
if [[ -n "$ZSH_VERSION" ]]; then
  setopt aliases
else
  shopt -s expand_aliases
fi

# Best effort applications - sync but don't wait for them to be healthy
BEST_EFFORT_APPS=(
    "devlake-peeks-hub"
    "grafana-dashboards-peeks-hub"
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
WAIT_TIMEOUT=3600  #(60 minutes)
CHECK_INTERVAL=30 # 30 seconds


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
                if [ "$ready_nodes" -gt 0 ]; then
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

    # Wait for ArgoCD to be fully ready first
    print_status "INFO" "Waiting for ArgoCD to be fully ready..."
    local argocd_ready=false
    local argocd_wait_time=0
    local argocd_max_wait=1200  # 20 minutes (increased from 15)
    
    while [ $argocd_wait_time -lt $argocd_max_wait ] && [ "$argocd_ready" = false ]; do
        # Check if ArgoCD namespace exists first
        if ! kubectl get namespace argocd >/dev/null 2>&1; then
            print_status "INFO" "ArgoCD namespace not found, waiting..."
            sleep 30
            argocd_wait_time=$((argocd_wait_time + 30))
            continue
        fi
        
        # Check if ArgoCD deployments exist and are ready with better error handling and retries
        local argocd_pods_ready="0"
        local argocd_repo_ready="0"
        local retry_count=0
        
        while [ $retry_count -lt 3 ]; do
            argocd_pods_ready=$(kubectl get deployment -n argocd argocd-server -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            argocd_repo_ready=$(kubectl get deployment -n argocd argocd-repo-server -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            
            # Handle empty responses (convert to 0)
            [ -z "$argocd_pods_ready" ] && argocd_pods_ready="0"
            [ -z "$argocd_repo_ready" ] && argocd_repo_ready="0"
            
            # If we got valid responses, break
            if [[ "$argocd_pods_ready" =~ ^[0-9]+$ ]] && [[ "$argocd_repo_ready" =~ ^[0-9]+$ ]]; then
                break
            fi
            
            retry_count=$((retry_count + 1))
            if [ $retry_count -lt 3 ]; then
                print_status "INFO" "kubectl query failed, retrying... ($retry_count/3)"
                sleep 5
            fi
        done
        
        # Check if ArgoCD API is responding with timeout
        local api_ready=false
        if timeout 10 kubectl get applications -n argocd >/dev/null 2>&1; then
            api_ready=true
        fi
        
        # Check if ArgoCD domain is available with improved logic
        local domain_available=false
        local domain_name=""
        
        # Try to get domain from secret first
        domain_name=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null || echo "")
        
        # If not found in secret, try CloudFront
        if [ -z "$domain_name" ] || [ "$domain_name" = "null" ]; then
            domain_name=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text 2>/dev/null || echo "")
        fi
        
        # Validate domain
        if [ -n "$domain_name" ] && [ "$domain_name" != "None" ] && [ "$domain_name" != "null" ] && [ "$domain_name" != "" ]; then
            domain_available=true
            print_status "INFO" "ArgoCD domain found: $domain_name"
        fi
        
        # More robust readiness check - require at least 1 pod for each deployment
        if [ "$argocd_pods_ready" -ge 1 ] && [ "$argocd_repo_ready" -ge 1 ] && [ "$api_ready" = true ] && [ "$domain_available" = true ]; then
            print_status "SUCCESS" "ArgoCD is ready (server: $argocd_pods_ready, repo: $argocd_repo_ready, api: responding, domain: $domain_name)"
            argocd_ready=true
        else
            print_status "INFO" "ArgoCD not ready yet (server: $argocd_pods_ready, repo: $argocd_repo_ready, api: $api_ready, domain: $domain_available), waiting..."
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

}

# Trap to handle script interruption
trap 'print_status "ERROR" "Bootstrap process interrupted"; show_final_status; exit 130' INT TERM

# Run main function
main "$@"
