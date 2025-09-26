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
MAX_RETRIES=3
RETRY_DELAY=45  # Increased from 30 to 45 seconds
SCRIPT_DIR="$(dirname "$0")"
WAIT_TIMEOUT=1800  #(30 minutes)
CHECK_INTERVAL=30 # 30 seconds


# Define scripts to run in order
SCRIPTS=(
    "1-backstage-build.sh"
    "2-tools-urls.sh"
)


# Main execution
main() {
    print_status "INFO" "Starting bootstrap deployment process"
    print_status "INFO" "Script directory: $SCRIPT_DIR"
    print_status "INFO" "Max retries per script: $MAX_RETRIES"
    print_status "INFO" "Retry delay: $RETRY_DELAY seconds"
    print_status "INFO" "ArgoCD wait timeout: $ARGOCD_WAIT_TIMEOUT seconds"
    print_status "INFO" "Scripts to execute: ${SCRIPTS[*]}"
    
    for cluster in "${CLUSTER_NAMES[@]}"; do
        configure_kubectl_with_fallback "$cluster"
    done

    #TODO: Switch the kubeconfig context to the hub cluster, first cluster is assumed as Hub cluster
    if ! kubectl config use-context "${CLUSTER_NAMES[0]}"; then
        print_status "ERROR" "Failed to switch kubeconfig context to ${CLUSTER_NAMES[0]}"
        exit 1
    fi

    source "$SCRIPT_DIR/0-backstage-build.sh"

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
                print_status "ERROR" "Backstage build timed out after ${build_timeout}s"
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

    # Update ENV variables
    print_step "Setting up environment variables for tools"
    export KEYCLOAKIDPPASSWORD=$(kubectl get secret keycloak-config -n keycloak -o jsonpath='{.data.USER_PASSWORD}' 2>/dev/null | base64 -d || echo "")
    export BACKSTAGEURL="https://$DOMAIN_NAME/backstage"
    export GITLABPW="$IDE_PASSWORD"
    export ARGOCDPW="$IDE_PASSWORD"
    export ARGOCDURL="https://$DOMAIN_NAME/argocd"
    export ARGOWFURL="https://$DOMAIN_NAME/argo-workflows"

    # ArgoCD environment variables for Backstage integration
    export ARGOCD_URL="https://$DOMAIN_NAME/argocd"
    export GIT_HOSTNAME=$(echo $GITLAB_URL | sed 's|https://||')
    export GIT_PASSWORD="$GITLAB_TOKEN"

    update_workshop_var "GRAFANAURL" "$GRAFANAURL"
    update_workshop_var "KEYCLOAKIDPPASSWORD" "$KEYCLOAKIDPPASSWORD"
    update_workshop_var "BACKSTAGEURL" "$BACKSTAGEURL"
    update_workshop_var "GITLABPW" "$GITLABPW"
    update_workshop_var "ARGOCDPW" "$ARGOCDPW"
    update_workshop_var "ARGOCDURL" "$ARGOCDURL"
    update_workshop_var "ARGOWFURL" "$ARGOWFURL"
    update_workshop_var "ARGOCD_URL" "$ARGOCD_URL"
    update_workshop_var "GIT_HOSTNAME" "$GIT_HOSTNAME"
    update_workshop_var "GIT_PASSWORD" "$GIT_PASSWORD"



    source /etc/profile.d/workshop.sh
    # Source all bashrc.d files
    for file in ~/.bashrc.d/*.sh; do
    [ -f "$file" ] && source "$file" || true
    done
}

# Trap to handle script interruption
trap 'print_status "ERROR" "Bootstrap process interrupted"; show_final_status; exit 130' INT TERM

# Run main function
main "$@"
