#!/bin/bash

#############################################################################
# ArgoCD and GitLab Setup Script
#############################################################################
#
# DESCRIPTION:
#   This script configures ArgoCD and GitLab for the EKS cluster management
#   environment. It:
#   1. Updates the kubeconfig to connect to the hub cluster
#   2. Retrieves and displays the ArgoCD URL and credentials
#   3. Sets up GitLab repository and SSH keys
#   4. Configures Git remote for the working repository
#   5. Creates a secret in ArgoCD for Git repository access
#   6. Logs in to ArgoCD CLI and lists applications
#
# USAGE:
#   ./1-argocd-gitlab-setup.sh
#
# PREREQUISITES:
#   - The management cluster must be created (run 0-initial-setup.sh first)
#   - Environment variables must be set:
#     - AWS_REGION: AWS region where resources are deployed
#     - WORKSPACE_PATH: Path to the workspace directory
#     - WORKING_REPO: Name of the working repository
#     - GIT_USERNAME: Git username for authentication
#     - IDE_PASSWORD: Password for ArgoCD and GitLab authentication
#
# SEQUENCE:
#   This is the second script (1) in the setup sequence.
#   Run after 0-initial-setup.sh and before 2-bootstrap-accounts.sh
#
#############################################################################
# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"
source "$SCRIPT_DIR/bootstrap-oidc-secrets.sh"

set -e
#set -x # debug

# Check for required dependencies
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed. Please install jq first."
    exit 1
fi

# Function to update or add environment variable to ~/.bashrc.d/platform.sh
update_workshop_var() {
    local var_name="$1"
    local var_value="$2"
    local workshop_file="$HOME/.bashrc.d/platform.sh"
    
    # Check if variable already exists in the file
    if grep -q "^export ${var_name}=" "$workshop_file" 2>/dev/null; then
        # Variable exists, update it
        sed -i "s|^export ${var_name}=.*|export ${var_name}=\"${var_value}\"|" "$workshop_file"
        print_info "Updated ${var_name} in ${workshop_file}"
    else
        # Variable doesn't exist, add it
        echo "export ${var_name}=\"${var_value}\"" >> "$workshop_file"
        print_info "Added ${var_name} to ${workshop_file}"
    fi
}

# Function to check if background build is still running
check_backstage_build_status() {
    if [ -n "$BACKSTAGE_BUILD_PID" ] && kill -0 $BACKSTAGE_BUILD_PID 2>/dev/null; then
        return 0  # Still running
    else
        return 1  # Finished or failed
    fi
}

print_header "ArgoCD and GitLab Setup"

print_step "Updating kubeconfig to connect to the hub cluster"
aws eks update-kubeconfig --name peeks-hub-cluster --alias peeks-hub-cluster

print_step "Creating Amazon Elastic Container Repository (Amazon ECR) for Backstage image"
aws ecr create-repository --repository-name peeks-backstage --region $AWS_REGION || true

print_step "Starting Backstage image build early"
print_info "Building Backstage image in background..."
# Create a temporary log file for the background build
BACKSTAGE_LOG="/tmp/backstage_build_$$.log"
BACKSTAGE_PATH="$(dirname "$SCRIPT_DIR")/backstage"
$SCRIPT_DIR/build_backstage.sh "$BACKSTAGE_PATH" > "$BACKSTAGE_LOG" 2>&1 &
BACKSTAGE_BUILD_PID=$!
print_info "Backstage build started with PID: $BACKSTAGE_BUILD_PID (logs: $BACKSTAGE_LOG)"

export DOMAIN_NAME=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text)
update_workshop_var "DOMAIN_NAME" "$DOMAIN_NAME"

print_header "Setting up GitLab repository and ArgoCD access"

export GITLAB_URL=https://$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'gitlab')].DomainName | [0]" --output text)
export NLB_DNS=$(aws elbv2 describe-load-balancers --region $AWS_REGION --names gitlab --query 'LoadBalancers[0].DNSName' --output text)
update_workshop_var "GITLAB_URL" "$GITLAB_URL"
update_workshop_var "NLB_DNS" "$NLB_DNS"
update_workshop_var "GIT_USERNAME" "user1"
update_workshop_var "WORKSPACE_PATH" "$HOME/environment" 
update_workshop_var "WORKING_REPO" "platform-on-eks-workshop"

source /etc/profile.d/workshop.sh
# Source all bashrc.d files
for file in ~/.bashrc.d/*.sh; do
  [ -f "$file" ] && source "$file" || true
done

print_info "Creating GitLab SSH keys"
$SCRIPT_DIR/gitlab_create_keys.sh

print_step "Configuring Git remote and pushing to GitLab"
cd $WORKSPACE_PATH/$WORKING_REPO
git remote rename origin github || true
git remote add origin ssh://git@$NLB_DNS/$GIT_USERNAME/$WORKING_REPO.git || true

print_step "Updating Backstage templates"
$SCRIPT_DIR/update_template_defaults.sh
git add . && git commit -m "Update Backstage Templates" || true

set -x
pwd
# Push the local branch (WORKSHOP_GIT_BRANCH) to the remote main branch
git push --set-upstream origin $WORKSHOP_GIT_BRANCH:main
set +x

print_step "Creating GitLab access token for ArgoCD"
ROOT_TOKEN="root-$IDE_PASSWORD"

# Get the user ID for the GIT_USERNAME
USER_ID=$(curl -sS -X GET "$GITLAB_URL/api/v4/users?username=$GIT_USERNAME" \
  -H "PRIVATE-TOKEN: $ROOT_TOKEN" | jq -r '.[0].id')

if [ "$USER_ID" = "null" ] || [ -z "$USER_ID" ]; then
    print_error "Failed to find user ID for username: $GIT_USERNAME"
    exit 1
fi

print_info "Found user ID $USER_ID for username $GIT_USERNAME"

# Create GitLab personal access token for ArgoCD repository access
GITLAB_TOKEN=$(curl -sS -X POST "$GITLAB_URL/api/v4/users/$USER_ID/personal_access_tokens" \
  -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "argocd-repository-access",
    "scopes": ["api", "read_repository", "write_repository"],
    "expires_at": "2025-12-31"
  }' | jq -r '.token')

if [ "$GITLAB_TOKEN" = "null" ] || [ -z "$GITLAB_TOKEN" ]; then
    print_error "Failed to create GitLab access token"
    exit 1
fi

print_info "GitLab access token created: $GITLAB_TOKEN"

# Store GitLab token in AWS Secrets Manager for use by other services (like Backstage)
print_step "Storing GitLab token in AWS Secrets Manager"
aws secretsmanager create-secret \
    --name "peeks-workshop-gitops-gitlab-pat" \
    --description "GitLab Personal Access Token for repository operations" \
    --secret-string "{\"token\":\"$GITLAB_TOKEN\",\"username\":\"$GIT_USERNAME\",\"hostname\":\"$(echo $GITLAB_URL | sed 's|https://||')\",\"working_repo\":\"$WORKING_REPO\"}" \
    --tags '[
        {"Key":"Environment","Value":"Platform"},
        {"Key":"Purpose","Value":"GitLab API Access"},
        {"Key":"ManagedBy","Value":"ArgoCD Setup Script"},
        {"Key":"Application","Value":"GitLab"}
    ]' \
    --region $AWS_REGION 2>/dev/null || \
aws secretsmanager update-secret \
    --secret-id "peeks-workshop-gitops-gitlab-pat" \
    --secret-string "{\"token\":\"$GITLAB_TOKEN\",\"username\":\"$GIT_USERNAME\",\"hostname\":\"$(echo $GITLAB_URL | sed 's|https://||')\",\"working_repo\":\"$WORKING_REPO\"}" \
    --region $AWS_REGION

print_success "GitLab token stored in AWS Secrets Manager: peeks-workshop-gitops-gitlab-pat"

# Test the token
print_info "Testing GitLab token access..."
TOKEN_TEST=$(curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$GITLAB_URL/api/v4/projects/$GIT_USERNAME%2F$WORKING_REPO" | jq -r '.path_with_namespace // .message')
if [ "$TOKEN_TEST" = "$GIT_USERNAME/$WORKING_REPO" ]; then
    print_success "GitLab token test successful"
else
    print_error "GitLab token test failed: $TOKEN_TEST"
    exit 1
fi

print_step "Creating ArgoCD Git repository secret with GitLab token"
envsubst << EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
   name: git-${WORKING_REPO}
   namespace: argocd
   labels:
      argocd.argoproj.io/secret-type: repository
stringData:
   url: ${GITLAB_URL}/${GIT_USERNAME}/${WORKING_REPO}.git
   type: git
   username: $GIT_USERNAME
   password: $GITLAB_TOKEN
EOF

print_step "Restarting ArgoCD repo server to pick up new credentials"
kubectl rollout restart deployment argocd-repo-server -n argocd

# Wait for rollout to complete with better error handling
print_info "Waiting for ArgoCD repo server rollout to complete..."
if ! kubectl rollout status deployment argocd-repo-server -n argocd --timeout=300s; then
    print_error "ArgoCD repo server rollout failed, attempting recovery..."
    
    # Check deployment status
    kubectl get deployment argocd-repo-server -n argocd -o wide
    kubectl get pods -l app.kubernetes.io/name=argocd-repo-server -n argocd
    
    # Try to wait for any ready pod with a longer timeout
    print_info "Waiting for any ArgoCD repo server pod to be ready..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-repo-server -n argocd --timeout=180s || {
        print_error "Failed to wait for ArgoCD repo server pod readiness"
        
        # Show pod logs for debugging
        print_info "Checking pod logs for troubleshooting..."
        kubectl logs -l app.kubernetes.io/name=argocd-repo-server -n argocd --tail=20 || true
        
        # Force delete old pods if they're stuck
        print_info "Attempting to force cleanup stuck pods..."
        kubectl delete pods -l app.kubernetes.io/name=argocd-repo-server -n argocd --grace-period=0 --force || true
        
        # Wait again after cleanup
        sleep 30
        kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-repo-server -n argocd --timeout=120s || {
            print_error "ArgoCD repo server restart failed completely"
            return 1
        }
    }
fi

print_success "ArgoCD repo server restarted successfully"

sleep 5

print_step "Pre-creating OIDC client secrets to break dependency cycles"
bootstrap_oidc_secrets

print_step "Logging in to ArgoCD CLI"
argocd login --username admin --password $IDE_PASSWORD --grpc-web-root-path /argocd $DOMAIN_NAME

print_info "Listing ArgoCD applications"
argocd app list

# Check build status
if check_backstage_build_status; then
    print_info "Backstage build is still running in parallel..."
fi

print_step "Syncing bootstrap application"
argocd app sync bootstrap

# Check build status again
if check_backstage_build_status; then
    print_info "Backstage build is still running in parallel..."
fi

print_info "Checking ArgoCD applications status"
kubectl get applications -n argocd

print_step "Ensuring critical ArgoCD applications are healthy"

# Define critical applications to monitor (can be customized)
CRITICAL_APPS="${CRITICAL_ARGOCD_APPS:-bootstrap cluster-addons argocd-peeks-hub-cluster ingress-nginx-peeks-hub-cluster}"
print_info "Monitoring applications: ${CRITICAL_APPS:-all applications}"

# Function to sync and wait for applications
sync_and_wait_apps() {
    local apps_to_check="$1"
    local max_attempts=3
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        print_info "Health check attempt $attempt/$max_attempts"
        
        # Get application status
        local app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null)
        
        # Filter for specific apps if provided, otherwise check all
        local unhealthy_apps
        if [ -n "$apps_to_check" ]; then
            unhealthy_apps=$(echo "$app_status" | grep -E "^($(echo "$apps_to_check" | tr ' ' '|')) " | awk '$2 != "Healthy" || $3 == "OutOfSync" {print $1}')
        else
            unhealthy_apps=$(echo "$app_status" | awk '$2 != "Healthy" || $3 == "OutOfSync" {print $1}')
        fi
        
        if [ -z "$unhealthy_apps" ]; then
            print_success "All monitored applications are healthy"
            return 0
        fi
        
        print_info "Syncing unhealthy applications:"
        echo "$unhealthy_apps" | while read app; do
            if [ -n "$app" ]; then
                print_info "  Syncing: $app"
                argocd app sync "$app" --timeout 60 2>/dev/null || {
                    print_warning "ArgoCD CLI sync failed for $app, using kubectl"
                    kubectl patch application "$app" -n argocd --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
                }
            fi
        done
        
        print_info "Waiting 60 seconds for sync operations..."
        sleep 60
        ((attempt++))
    done
    
    print_warning "Some applications may still be unhealthy after $max_attempts attempts"
    return 1
}

# Run health check
sync_and_wait_apps "$CRITICAL_APPS"

# Show final status
print_info "Final applications status:"
kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status" --no-headers

print_step "Waiting for Backstage image build to complete"
print_info "Checking if Backstage build is still running..."

# Check if the process is still running
if kill -0 $BACKSTAGE_BUILD_PID 2>/dev/null; then
    print_info "Backstage build is still running, waiting for completion..."
    if wait $BACKSTAGE_BUILD_PID; then
        print_success "Backstage image build completed successfully"
        # Show the last few lines of the build log for confirmation
        print_info "Build log summary:"
        tail -n 5 "$BACKSTAGE_LOG" | sed 's/^/  /'
    else
        print_error "Backstage image build failed"
        print_error "Build log (last 20 lines):"
        tail -n 20 "$BACKSTAGE_LOG" | sed 's/^/  /'
        exit 1
    fi
else
    # Process already finished, check exit status
    if wait $BACKSTAGE_BUILD_PID; then
        print_success "Backstage image build already completed successfully"
    else
        print_error "Backstage image build failed"
        print_error "Build log (last 20 lines):"
        tail -n 20 "$BACKSTAGE_LOG" | sed 's/^/  /'
        exit 1
    fi
fi

# Clean up the temporary log file
rm -f "$BACKSTAGE_LOG"

print_step "Updating Backstage template with environment-specific values"
# Run the template update script to replace placeholder values with actual environment values
if [ -f "$WORKSPACE_PATH/$WORKING_REPO/scripts/update_template_defaults.sh" ]; then
    cd "$WORKSPACE_PATH/$WORKING_REPO"
    ./scripts/update_template_defaults.sh
    
    # Commit the updated template
    print_info "Committing updated Backstage template to Git repository"
    git add platform/backstage/templates/eks-cluster-template/template.yaml
    git commit -m "Update Backstage template with environment-specific values

- Account ID: $ACCOUNT_ID (actual environment value)
- GitLab domain: Updated to actual CloudFront domain
- Ingress domain: Updated to actual ingress domain  
- Repository URLs: Updated to use actual GitLab domain

This ensures templates work correctly without placeholder URL errors." || print_info "No changes to commit (template already updated)"
    
    git push origin $WORKSHOP_GIT_BRANCH:main || print_warning "Failed to push template updates (may already be up to date)"
    
    print_success "Backstage template updated with environment values"
else
    print_warning "Template update script not found, skipping template update"
fi

# Export additional environment variables for tools
print_step "Setting up environment variables for tools"
export KEYCLOAKIDPPASSWORD=$(kubectl get secret keycloak-config -n keycloak -o jsonpath='{.data.USER_PASSWORD}' 2>/dev/null | base64 -d || echo "")
export BACKSTAGEURL="https://$DOMAIN_NAME/backstage"
export GITLABPW="$IDE_PASSWORD"
export ARGOCDPW="$IDE_PASSWORD"
export ARGOCDURL="https://$DOMAIN_NAME/argocd"
export ARGOWFURL="https://$DOMAIN_NAME/argo-workflows"

update_workshop_var "KEYCLOAKIDPPASSWORD" "$KEYCLOAKIDPPASSWORD"
update_workshop_var "BACKSTAGEURL" "$BACKSTAGEURL"
update_workshop_var "GITLABPW" "$GITLABPW"
update_workshop_var "ARGOCDPW" "$ARGOCDPW"
update_workshop_var "ARGOCDURL" "$ARGOCDURL"
update_workshop_var "ARGOWFURL" "$ARGOWFURL"

print_success "ArgoCD and GitLab setup completed successfully."

print_header "Access Information"
print_info "You can connect to Argo CD UI and check everything is ok"
echo -e "${CYAN}ArgoCD URL:${BOLD} https://$DOMAIN_NAME/argocd${NC}"
echo -e "${CYAN}   Login:${BOLD} admin${NC}"
echo -e "${CYAN}   Password:${BOLD} $IDE_PASSWORD${NC}"

print_info "Next step: Run 2-bootstrap-accounts.sh to bootstrap management and spoke accounts."
