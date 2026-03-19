#!/bin/bash

# Timestamp function for performance tracking
log_timestamp() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Enable alias expansion in non-interactive shell
if [[ -n "$ZSH_VERSION" ]]; then
  setopt aliases
else
  shopt -s expand_aliases
fi

# Best effort applications - sync but don't wait for them to be healthy
# These apps may take longer to deploy or have known issues that don't block the workshop
BEST_EFFORT_APPS=(
    "image-prepuller-${RESOURCE_PREFIX}-hub"  # Truly optional - only for performance
)

# Apps that are OK if Healthy but OutOfSync (known ArgoCD ignore issues)
# These must have: status.health.status == "Healthy" AND status.operationState.phase == "Succeeded"
HEALTHY_OUTOFSYNC_OK_APPS=(
    "keycloak-${RESOURCE_PREFIX}-hub"
    "backstage-${RESOURCE_PREFIX}-hub"
)

# Export for use in sourced scripts
export BEST_EFFORT_APPS
export HEALTHY_OUTOFSYNC_OK_APPS

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


# Track clusters that needed SG fixes (used in final status)
SG_FIXED_CLUSTERS=()

# Verify that each EKS cluster's managed security group has the self-referencing
# ingress rule required for node-to-node and control-plane-to-node communication.
# EKS Auto Mode adds this rule automatically, but it can silently fail during
# parallel cluster creation due to API throttling or transient errors.
verify_cluster_security_groups() {
    print_status "INFO" "Checking EKS cluster security groups for self-referencing ingress rules..."
    for cluster_name in "${CLUSTER_NAMES[@]}"; do
        local cluster_sg
        cluster_sg=$(aws eks describe-cluster --name "$cluster_name" --region "$AWS_DEFAULT_REGION" \
            --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId' --output text 2>/dev/null)

        if [ -z "$cluster_sg" ] || [ "$cluster_sg" = "None" ]; then
            print_status "WARNING" "Could not retrieve security group for cluster $cluster_name"
            continue
        fi

        # Check if self-referencing ingress rule exists using JSON output for reliable parsing
        local has_self_ref
        has_self_ref=$(aws ec2 describe-security-group-rules --region "$AWS_DEFAULT_REGION" \
            --filters "Name=group-id,Values=$cluster_sg" --output json 2>/dev/null | \
            jq --arg sg "$cluster_sg" '[.SecurityGroupRules[] | select(.IsEgress==false and .IpProtocol=="-1" and .ReferencedGroupInfo.GroupId==$sg)] | length')

        if [ "${has_self_ref:-0}" -eq 0 ]; then
            print_status "WARNING" "Cluster $cluster_name ($cluster_sg) is MISSING self-referencing ingress rule!"
            print_status "WARNING" "This blocks webhooks and kubelet communication. Fixing now..."
            if aws ec2 authorize-security-group-ingress --region "$AWS_DEFAULT_REGION" \
                --group-id "$cluster_sg" --protocol -1 --source-group "$cluster_sg" >/dev/null 2>&1; then
                print_status "SUCCESS" "Added self-referencing ingress rule to $cluster_sg for cluster $cluster_name"
                SG_FIXED_CLUSTERS+=("$cluster_name")
            else
                print_status "ERROR" "Failed to add self-referencing ingress rule to $cluster_sg for cluster $cluster_name"
            fi
        else
            print_status "SUCCESS" "Cluster $cluster_name ($cluster_sg) security group OK"
        fi
    done
}

# Main execution
main() {
    log_timestamp "=== SCRIPT START ==="
    print_status "INFO" "Starting bootstrap deployment process"
    print_status "INFO" "Script directory: $SCRIPT_DIR"
    print_status "INFO" "ArgoCD re-check interval: $CHECK_INTERVAL seconds"
    print_status "INFO" "ArgoCD apps wait timeout: $WAIT_TIMEOUT seconds"

    source "$SCRIPT_DIR/backstage-utils.sh"

    # Ensure clusters are fully ready before proceeding
    log_timestamp "Phase: Verifying cluster readiness"
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
                local ready_nodes=$(kubectl get nodes --no-headers 2>/dev/null | { grep -c "Ready" || true; })
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
    
    # Verify and fix EKS cluster security group self-referencing rules
    log_timestamp "Phase: Verifying EKS cluster security groups"
    verify_cluster_security_groups

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
    log_timestamp "Phase: Waiting for ArgoCD EKS capability"
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

    # Ensure the default AppProject exists (EKS ArgoCD Capability may not create it automatically)
    if ! kubectl get appproject default -n argocd >/dev/null 2>&1; then
        print_status "WARNING" "default AppProject not found, creating it..."
        kubectl apply -f - <<'APPPROJ'
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: default
  namespace: argocd
spec:
  clusterResourceWhitelist:
  - group: '*'
    kind: '*'
  destinations:
  - namespace: '*'
    server: '*'
  sourceNamespaces:
  - argocd
  sourceRepos:
  - '*'
APPPROJ
        print_status "SUCCESS" "default AppProject created"
    else
        print_status "INFO" "default AppProject already exists"
    fi

    # ---------------------------------------------------------------------------
    # Phase: Configure IAM Identity Center + retrieve ArgoCD auth token
    # ---------------------------------------------------------------------------
    log_timestamp "Phase: IAM Identity Center configuration and ArgoCD token retrieval"

    if wait_for_keycloak_ready 900 30; then
        # Resolve IDC instance ID
        local idc_instance_arn
        idc_instance_arn=$(aws sso-admin list-instances --query 'Instances[0].InstanceArn' --output text 2>/dev/null || echo "None")
        local idc_instance_id=""
        if [ -n "$idc_instance_arn" ] && [ "$idc_instance_arn" != "None" ]; then
            idc_instance_id=$(echo "$idc_instance_arn" | grep -oP '[0-9a-f]{16}$' || echo "")
            if [ -z "$idc_instance_id" ]; then
                idc_instance_id=$(echo "$idc_instance_arn" | awk -F'/' '{print $NF}' | sed 's/^ssoins-//')
            fi
        fi

        # Resolve domain name (same pattern as argocd-utils.sh wait_for_argocd_apps_health)
        local domain_name
        domain_name=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null || echo "")
        if [ -z "$domain_name" ] || [ "$domain_name" = "null" ]; then
            domain_name=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text 2>/dev/null || echo "")
        fi

        # Resolve Keycloak admin password
        local keycloak_admin_password
        keycloak_admin_password=$(kubectl get secret keycloak-config -n keycloak -o jsonpath='{.data.KC_BOOTSTRAP_ADMIN_PASSWORD}' 2>/dev/null | base64 -d || echo "")

        if [ -z "$idc_instance_id" ] || [ -z "$domain_name" ] || [ "$domain_name" = "None" ] || [ -z "$keycloak_admin_password" ]; then
            print_status "WARNING" "Missing parameters for Identity Center configuration (instance_id=$idc_instance_id, domain=$domain_name, kc_password set=$([ -n "$keycloak_admin_password" ] && echo yes || echo no))"
        else
            # Fetch AWS credentials from SSM Parameter Store
            print_status "INFO" "Fetching AWS credentials from SSM Parameter Store..."
            if aws ssm get-parameter --name "/${RESOURCE_PREFIX}/keycloak-idc-integration-credentials" --with-decryption --query 'Parameter.Value' --output text | jq > /tmp/keycloak-idc-integration-credentials.json 2>/dev/null; then
                print_status "SUCCESS" "AWS credentials retrieved and saved to /tmp/keycloak-idc-integration-credentials.json"
                
                # Run configure_identity_center.py with up to 3 retries, 5 min wait between
                local idc_success=false
                local idc_attempt=0
                local idc_max_retries=5
                local idc_retry_wait=120  # 2 minutes

                while [ $idc_attempt -lt $idc_max_retries ] && [ "$idc_success" = false ]; do
                    idc_attempt=$((idc_attempt + 1))
                    print_status "INFO" "Running configure_identity_center.py (attempt $idc_attempt/$idc_max_retries)..."

                    if python3 "${SCRIPT_DIR}/configure_identity_center.py" \
                    --region "$AWS_REGION" \
                    --instance-id "$idc_instance_id" \
                    --keycloak-dns "$domain_name" \
                    --keycloak-admin-password="$keycloak_admin_password"; then
                    print_status "SUCCESS" "IAM Identity Center configuration completed"
                    idc_success=true
                else
                    print_status "WARNING" "configure_identity_center.py failed (attempt $idc_attempt/$idc_max_retries)"
                    if [ $idc_attempt -lt $idc_max_retries ]; then
                        print_status "INFO" "Retrying in $((idc_retry_wait / 60)) minutes..."
                        sleep $idc_retry_wait
                    fi
                fi
            done

            if [ "$idc_success" = false ]; then
                print_status "WARNING" "IAM Identity Center configuration failed after $idc_max_retries attempts, continuing without it"
            fi
            else
                print_status "ERROR" "Failed to retrieve AWS credentials from SSM Parameter Store"
                print_status "WARNING" "Skipping Identity Center configuration"
            fi
        fi

        # Retrieve ArgoCD auth token via browser automation
        print_status "INFO" "Retrieving ArgoCD authentication token..."
        local argocd_server_url
        argocd_server_url=$(aws eks describe-capability --cluster-name "${RESOURCE_PREFIX}-hub" --capability-name argocd --query 'capability.configuration.argoCd.serverUrl' --output text 2>/dev/null || echo "")

        if [ -n "$argocd_server_url" ] && [ "$argocd_server_url" != "None" ]; then
            local argocd_token
            argocd_token=$(python3 "${SCRIPT_DIR}/argocd_token_automation.py" \
                --url "$argocd_server_url" \
                --username "user1" \
                --password "${USER1_PASSWORD}" \
                --output token 2>/dev/null || echo "")

            if [ -n "$argocd_token" ]; then
                export ARGOCD_AUTH_TOKEN="$argocd_token"
                export ARGOCD_SERVER=$(echo "$argocd_server_url" | sed 's|https://||' | sed 's|/.*||')
                print_status "SUCCESS" "ArgoCD auth token retrieved and exported"
                update_workshop_var "ARGOCD_AUTH_TOKEN" "$ARGOCD_AUTH_TOKEN"
                update_workshop_var "ARGOCD_SERVER" "$ARGOCD_SERVER"
                update_workshop_var "ARGOCD_OPTS" "${ARGOCD_OPTS:---grpc-web}"
            else
                print_status "WARNING" "Failed to retrieve ArgoCD token, continuing without CLI authentication"
            fi
        else
            print_status "WARNING" "ArgoCD server URL not available, skipping token retrieval"
        fi
    else
        print_status "WARNING" "Skipping Identity Center configuration and ArgoCD token retrieval"
    fi

    # Dependency-aware ArgoCD app synchronization
    wait_for_argocd_apps_with_dependencies

    # Run enhanced recovery to handle any remaining issues
    log_timestamp "Phase: Enhanced ArgoCD Recovery"
    print_status "INFO" "Running enhanced ArgoCD recovery to ensure all apps are healthy..."
    "${SCRIPT_DIR}/recover-argocd-apps.sh"
    
    # Verify final application health
    # Count apps that are Healthy+Synced OR Healthy+OutOfSync with Succeeded operation (known false drift)
    local total_apps=$(kubectl get applications -n argocd --no-headers 2>/dev/null | wc -l)
    local healthy_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | jq '[.items[] | select(
        .status.health.status == "Healthy" and (
            .status.sync.status == "Synced" or
            (.status.operationState.phase == "Succeeded")
        )
    )] | length')
    
    if [ "$healthy_apps" -eq "$total_apps" ]; then
        print_status "SUCCESS" "All $total_apps ArgoCD applications are healthy!"
    else
        print_status "WARNING" "$healthy_apps/$total_apps applications are healthy. Some apps may still be deploying."
    fi

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
    log_timestamp "Phase: Final workshop validation"
    print_status "INFO" "Running final workshop validation..."
    if bash "$SCRIPT_DIR/check-workshop-setup.sh"; then
        log_timestamp "=== SCRIPT COMPLETED SUCCESSFULLY ==="
        print_status "SUCCESS" "Workshop setup validation completed - all components healthy!"
    else
        log_timestamp "=== SCRIPT COMPLETED WITH WARNINGS ==="
        print_status "WARNING" "Workshop setup validation found issues - check output above"
        print_status "INFO" "You can run 'check-workshop-setup' command later to verify"
    fi

}

# Trap to handle script interruption
trap 'print_status "ERROR" "Bootstrap process interrupted"; show_final_status; exit 130' INT TERM

# Run main function
main "$@"
