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
#   3. Sets up GitLab repository for HTTPS access
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

# Configuration
STUCK_SYNC_TIMEOUT=${STUCK_SYNC_TIMEOUT:-180}  # 3 minutes default for stuck sync operations

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
aws eks update-kubeconfig --name ${RESOURCE_PREFIX}-hub-cluster --alias ${RESOURCE_PREFIX}-hub-cluster

print_step "Creating Amazon Elastic Container Repository (Amazon ECR) for Backstage image"
aws ecr create-repository --repository-name ${RESOURCE_PREFIX}-backstage --region $AWS_REGION || true

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

export GITLAB_URL=https://$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, 'gitlab')].DomainName | [0]" --output text)
update_workshop_var "GITLAB_URL" "$GITLAB_URL"

# Get Grafana workspace ID and set as environment variable
print_info "Retrieving Grafana workspace ID..."
export WORKSPACE_ID=$(aws grafana list-workspaces --region $AWS_REGION --query "workspaces[?contains(name, '${RESOURCE_PREFIX:-peeks}')].id | [0]" --output text 2>/dev/null || echo "")
if [ -n "$WORKSPACE_ID" ] && [ "$WORKSPACE_ID" != "None" ] && [ "$WORKSPACE_ID" != "null" ]; then
    print_info "Found Grafana workspace ID: $WORKSPACE_ID"
    update_workshop_var "WORKSPACE_ID" "$WORKSPACE_ID"
else
    print_warning "Grafana workspace not found or not yet created"
    export WORKSPACE_ID=""
    update_workshop_var "WORKSPACE_ID" ""
fi
update_workshop_var "GIT_USERNAME" "user1"
update_workshop_var "WORKSPACE_PATH" "$HOME/environment" 
update_workshop_var "WORKING_REPO" "platform-on-eks-workshop"
update_workshop_var "KEYCLOAK_NAMESPACE" "keycloak"
update_workshop_var "KEYCLOAK_REALM" "platform"
update_workshop_var "KEYCLOAK_USER_ADMIN_PASSWORD" $(openssl rand -base64 8)
update_workshop_var "KEYCLOAK_USER_EDITOR_PASSWORD" $(openssl rand -base64 8)
update_workshop_var "KEYCLOAK_USER_VIEWER_PASSWORD" $(openssl rand -base64 8)

# Get Grafana workspace endpoint from AWS CLI
print_info "Retrieving Grafana workspace endpoint..."
GRAFANA_WORKSPACE_ID=$(aws grafana list-workspaces --region $AWS_REGION --query "workspaces[?name=='${RESOURCE_PREFIX:-peeks}-observability'].id" --output text 2>/dev/null || echo "")
if [ -n "$GRAFANA_WORKSPACE_ID" ] && [ "$GRAFANA_WORKSPACE_ID" != "None" ]; then
    export GRAFANAURL=$(aws grafana describe-workspace --workspace-id "$GRAFANA_WORKSPACE_ID" --region $AWS_REGION --query "workspace.endpoint" --output text 2>/dev/null || echo "")
    if [ -n "$GRAFANAURL" ]; then
        print_info "Grafana workspace endpoint: $GRAFANAURL"
    else
        print_warning "Could not retrieve Grafana workspace endpoint"
    fi
else
    print_warning "Grafana workspace '${RESOURCE_PREFIX:-peeks}-observability' not found"
fi

# Save Grafana URL if available
if [ -n "$GRAFANAURL" ]; then
    update_workshop_var "GRAFANAURL" "$GRAFANAURL"
fi

source /etc/profile.d/workshop.sh
# Source all bashrc.d files
for file in ~/.bashrc.d/*.sh; do
  [ -f "$file" ] && source "$file" || true
done

print_info "Using HTTPS for GitLab operations (SSH keys not required)"
# HTTPS authentication will use GitLab tokens instead of SSH keys

print_step "Configuring Git credentials for HTTPS access"
# Configure Git credentials for HTTPS authentication
git config --global credential.helper store
git config --global user.name "$GIT_USERNAME"
git config --global user.email "$GIT_USERNAME@workshop.local"

# Create credentials file for HTTPS access using root token initially
GITLAB_DOMAIN=$(echo "$GITLAB_URL" | sed 's|https://||')
echo "https://root:$IDE_PASSWORD@$GITLAB_DOMAIN" > ~/.git-credentials

print_step "Ensuring GitLab repository exists"
# Check if repository exists, create if it doesn't
REPO_CHECK=$(curl -s -H "PRIVATE-TOKEN: root-$IDE_PASSWORD" "$GITLAB_URL/api/v4/projects/$GIT_USERNAME%2F$WORKING_REPO" | jq -r '.path_with_namespace // .message')
if [ "$REPO_CHECK" != "$GIT_USERNAME/$WORKING_REPO" ]; then
    print_info "Repository doesn't exist, creating it..."
    CREATE_REPO=$(curl -s -X POST "$GITLAB_URL/api/v4/projects" \
        -H "PRIVATE-TOKEN: root-$IDE_PASSWORD" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"$WORKING_REPO\",
            \"path\": \"$WORKING_REPO\",
            \"namespace_id\": 2,
            \"visibility\": \"internal\",
            \"initialize_with_readme\": false
        }" | jq -r '.path_with_namespace // .message')
    
    if [ "$CREATE_REPO" = "$GIT_USERNAME/$WORKING_REPO" ]; then
        print_success "Repository created successfully"
    else
        print_error "Failed to create repository: $CREATE_REPO"
        exit 1
    fi
else
    print_info "Repository already exists"
fi

print_step "Configuring Git remote and pushing to GitLab"
cd $WORKSPACE_PATH/$WORKING_REPO
git remote rename origin github || true
git remote add origin $GITLAB_URL/$GIT_USERNAME/$WORKING_REPO.git || true

print_step "Updating Backstage templates"
$SCRIPT_DIR/update_template_defaults.sh
git add . && git commit -m "Update Backstage Templates" || true

# Push the local branch (WORKSHOP_GIT_BRANCH) to the remote main branch
print_info "Pushing to GitLab using HTTPS authentication..."
git push --set-upstream origin $WORKSHOP_GIT_BRANCH:main


print_step "Creating GitLab access token for ArgoCD"
ROOT_TOKEN="root-$IDE_PASSWORD"

# Check if GitLab token already exists in Secrets Manager
EXISTING_SECRET=$(aws secretsmanager get-secret-value --secret-id "${RESOURCE_PREFIX:-peeks}-gitlab-pat" --region $AWS_REGION 2>/dev/null || echo "")

if [ -n "$EXISTING_SECRET" ]; then
    GITLAB_TOKEN=$(echo "$EXISTING_SECRET" | jq -r '.SecretString | fromjson | .token')
    print_info "Using existing GitLab token from Secrets Manager"
    
    # Test the existing token
    print_info "Testing existing GitLab token access..."
    TOKEN_TEST=$(curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$GITLAB_URL/api/v4/projects/$GIT_USERNAME%2F$WORKING_REPO" | jq -r '.path_with_namespace // .message')
    if [ "$TOKEN_TEST" = "$GIT_USERNAME/$WORKING_REPO" ]; then
        print_success "Existing GitLab token test successful"
        # Skip token creation - jump to ArgoCD secret creation
        SKIP_TOKEN_CREATION=true
    else
        print_info "Existing token invalid, creating new one..."
        EXISTING_SECRET=""
        SKIP_TOKEN_CREATION=false
    fi
else
    SKIP_TOKEN_CREATION=false
fi

if [ "$SKIP_TOKEN_CREATION" != "true" ]; then
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
fi

# Store GitLab token in AWS Secrets Manager for use by other services (like Backstage)
if [ -z "$EXISTING_SECRET" ]; then
    print_step "Storing GitLab token in AWS Secrets Manager"
    aws secretsmanager create-secret \
        --name "${RESOURCE_PREFIX:-peeks}-gitlab-pat" \
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
        --secret-id "${RESOURCE_PREFIX:-peeks}-gitlab-pat" \
        --secret-string "{\"token\":\"$GITLAB_TOKEN\",\"username\":\"$GIT_USERNAME\",\"hostname\":\"$(echo $GITLAB_URL | sed 's|https://||')\",\"working_repo\":\"$WORKING_REPO\"}" \
        --region $AWS_REGION

    print_success "GitLab token stored in AWS Secrets Manager: ${RESOURCE_PREFIX:-peeks}-gitlab-pat"
else
    print_info "Using existing GitLab token from Secrets Manager"
fi

# Test the token
print_info "Testing GitLab token access..."
TOKEN_TEST=$(curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$GITLAB_URL/api/v4/projects/$GIT_USERNAME%2F$WORKING_REPO" | jq -r '.path_with_namespace // .message')
if [ "$TOKEN_TEST" = "$GIT_USERNAME/$WORKING_REPO" ]; then
    print_success "GitLab token test successful"
    
    # Update Git credentials to use the user token instead of root token
    print_info "Updating Git credentials to use user token..."
    GITLAB_DOMAIN=$(echo "$GITLAB_URL" | sed 's|https://||')
    echo "https://$GIT_USERNAME:$GITLAB_TOKEN@$GITLAB_DOMAIN" > ~/.git-credentials
    print_success "Git credentials updated for user token authentication"
else
    print_error "GitLab token test failed: $TOKEN_TEST"
    exit 1
fi

print_step "Creating ArgoCD Git repository secret with GitLab token"

# Check if secret already exists and get its current token
EXISTING_TOKEN=""
if kubectl get secret git-${WORKING_REPO} -n argocd >/dev/null 2>&1; then
    EXISTING_TOKEN=$(kubectl get secret git-${WORKING_REPO} -n argocd -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
fi

# Apply the secret
SECRET_OUTPUT=$(envsubst << EOF | kubectl apply -f -
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
)

echo "$SECRET_OUTPUT"

# Check if restart is needed
RESTART_NEEDED=false
if echo "$SECRET_OUTPUT" | grep -q "created"; then
    print_info "New secret created, ArgoCD restart required"
    RESTART_NEEDED=true
elif echo "$SECRET_OUTPUT" | grep -q "configured"; then
    if [ "$EXISTING_TOKEN" != "$GITLAB_TOKEN" ]; then
        print_info "Secret token changed, ArgoCD restart required"
        RESTART_NEEDED=true
    else
        print_info "Secret exists with same token, skipping ArgoCD restart"
    fi
fi

if [ "$RESTART_NEEDED" = true ]; then
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
else
    print_success "ArgoCD repo server restart not needed"
fi

sleep 5

print_step "Pre-creating OIDC client secrets to break dependency cycles"
bootstrap_oidc_secrets

print_step "Logging in to ArgoCD CLI"
argocd login --username admin --password $IDE_PASSWORD --grpc-web-root-path /argocd $DOMAIN_NAME

print_info "Listing ArgoCD applications"
argocd app list

print_step "Creating ArgoCD token for Backstage integration"
# Check if ArgoCD token already exists in Secrets Manager
EXISTING_ARGOCD_SECRET=$(aws secretsmanager get-secret-value --secret-id "${RESOURCE_PREFIX:-peeks}-argocd-token" --region $AWS_REGION 2>/dev/null || echo "")

if [ -n "$EXISTING_ARGOCD_SECRET" ]; then
    ARGOCD_TOKEN=$(echo "$EXISTING_ARGOCD_SECRET" | jq -r '.SecretString | fromjson | .token')
    print_info "Using existing ArgoCD token from Secrets Manager"
else
    # Create a service account for Backstage
    print_info "Creating ArgoCD service account for Backstage"
    kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: backstage
  namespace: argocd
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: backstage-argocd
rules:
- apiGroups: ["argoproj.io"]
  resources: ["applications", "appprojects"]
  verbs: ["get", "list", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: backstage-argocd
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: backstage-argocd
subjects:
- kind: ServiceAccount
  name: backstage
  namespace: argocd
EOF

    # Wait for service account to be ready
    sleep 5

    # Get the service account token
    ARGOCD_TOKEN=$(kubectl create token backstage -n argocd --duration=8760h) # 1 year token
    
    if [ -z "$ARGOCD_TOKEN" ]; then
        print_error "Failed to create ArgoCD token"
        exit 1
    fi

    # Store ArgoCD token in AWS Secrets Manager
    print_info "Storing ArgoCD token in AWS Secrets Manager"
    aws secretsmanager create-secret \
        --name "${RESOURCE_PREFIX:-peeks}-argocd-token" \
        --description "ArgoCD Service Account Token for Backstage integration" \
        --secret-string "{\"token\":\"$ARGOCD_TOKEN\",\"url\":\"$ARGOCD_URL\",\"service_account\":\"backstage\"}" \
        --tags '[
            {"Key":"Environment","Value":"Platform"},
            {"Key":"Purpose","Value":"ArgoCD API Access"},
            {"Key":"ManagedBy","Value":"ArgoCD Setup Script"},
            {"Key":"Application","Value":"Backstage"}
        ]' \
        --region $AWS_REGION

    print_success "ArgoCD token created and stored in Secrets Manager: ${RESOURCE_PREFIX:-peeks}-argocd-token"
fi

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

# Function to fix git revision conflicts
fix_git_revision_conflicts() {
    print_info "Checking for git revision conflicts..."
    
    # Get all applications with comparison errors
    local apps_with_errors=$(kubectl get applications -n argocd -o json | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type == "ComparisonError" and (.message | contains("cannot reference a different revision")))) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$apps_with_errors" ]; then
        print_warning "Found applications with git revision conflicts: $apps_with_errors"
        echo "$apps_with_errors" | while read -r app; do
            print_info "Fixing revision conflict for $app"
            # Hard refresh to latest revision
            kubectl patch application "$app" -n argocd --type merge -p '{"spec":{"sources":[{"targetRevision":"HEAD"},{"targetRevision":"HEAD"}]}}' 2>/dev/null || true
            kubectl patch application "$app" -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD","prune":true}}}' 2>/dev/null || true
            sleep 3
        done
        sleep 10
    fi
}

# Function to ensure ApplicationSets exist
ensure_applicationsets() {
    print_info "Ensuring ApplicationSets are properly created..."
    
    # Check if bootstrap is healthy first
    local bootstrap_status=$(kubectl get application bootstrap -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null || echo "Unknown")
    
    if [ "$bootstrap_status" != "Healthy" ]; then
        print_warning "Bootstrap application is not healthy ($bootstrap_status), syncing..."
        kubectl patch application bootstrap -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD","prune":true}}}' 2>/dev/null || true
        
        # Wait for bootstrap to become healthy
        local wait_count=0
        while [ $wait_count -lt 30 ]; do
            bootstrap_status=$(kubectl get application bootstrap -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null || echo "Unknown")
            if [ "$bootstrap_status" = "Healthy" ]; then
                print_success "Bootstrap application is now healthy"
                break
            fi
            print_info "Waiting for bootstrap to become healthy... ($bootstrap_status)"
            sleep 10
            wait_count=$((wait_count + 1))
        done
    fi
    
    # Check for required ApplicationSets
    local required_appsets="cluster-addons"
    for appset in $required_appsets; do
        if ! kubectl get applicationset "$appset" -n argocd >/dev/null 2>&1; then
            print_warning "ApplicationSet $appset not found, forcing bootstrap refresh..."
            kubectl patch application bootstrap -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD","prune":true}}}' 2>/dev/null || true
            sleep 15
            break
        fi
    done
}

# Run the fixes before monitoring
fix_git_revision_conflicts
ensure_applicationsets

# Define critical applications to monitor (can be customized)
CRITICAL_APPS="${CRITICAL_ARGOCD_APPS:-bootstrap cluster-addons argocd-${RESOURCE_PREFIX}-hub-cluster ingress-nginx-${RESOURCE_PREFIX}-hub-cluster}"
print_info "Monitoring applications: ${CRITICAL_APPS:-all applications}"

# Function to sync and wait for applications with 80% healthy threshold
sync_and_wait_apps() {
    local apps_to_check="$1"
    local max_attempts=3
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        print_info "Health check attempt $attempt/$max_attempts"
        
        # Enhanced stuck operation handling
        print_info "Checking for stuck operations and revision conflicts..."
        
        # Terminate stuck operations (running > 3 minutes)
        local stuck_apps=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.operationState.phase}{" "}{.status.operationState.startedAt}{"\n"}{end}' 2>/dev/null | \
            awk -v now=$(date +%s) '$2=="Running" && (now - mktime(gensub(/[-T:Z]/, " ", "g", $3))) > 180 {print $1}')
        
        if [ -n "$stuck_apps" ]; then
            echo "$stuck_apps" | while read -r app; do
                print_warning "Terminating stuck sync for $app (running > 180s)"
                kubectl patch application "$app" -n argocd --type merge -p '{"operation":null}' 2>/dev/null || true
            done
            sleep 5
        fi
        
        # Handle revision conflicts and comparison errors
        local error_apps=$(kubectl get applications -n argocd -o json | jq -r '.items[] | select(.status.conditions[]? | select(.type == "ComparisonError")) | .metadata.name' 2>/dev/null || echo "")
        
        if [ -n "$error_apps" ]; then
            echo "$error_apps" | while read -r app; do
                print_warning "Fixing revision conflict for $app"
                # Force refresh to resolve revision conflicts
                kubectl patch application "$app" -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
                sleep 2
            done
        fi
        
        # Check for missing ApplicationSets and recreate them
        local missing_appsets=$(kubectl get applications -n argocd -o json | jq -r '.items[] | select(.status.conditions[]? | select(.message | contains("ApplicationSet") and contains("not found"))) | .metadata.name' 2>/dev/null || echo "")
        
        if [ -n "$missing_appsets" ]; then
            print_warning "Found applications with missing ApplicationSets, forcing bootstrap refresh..."
            # Refresh bootstrap application to recreate ApplicationSets
            kubectl patch application bootstrap -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
            sleep 10
        fi
        
        # Get application status
        local app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null)
        
        # Count healthy vs total apps
        local total_apps=0
        local healthy_apps=0
        local synced_apps=0
        local unhealthy_apps=()
        
        while IFS=' ' read -r app health sync; do
            [ -z "$app" ] && continue
            total_apps=$((total_apps + 1))
            
            if [ "$health" = "Healthy" ]; then
                healthy_apps=$((healthy_apps + 1))
            fi
            
            if [ "$sync" = "Synced" ]; then
                synced_apps=$((synced_apps + 1))
            fi
            
            # Track unhealthy apps for syncing
            if [ "$health" != "Healthy" ] || [ "$sync" = "OutOfSync" ]; then
                unhealthy_apps+=("$app")
            fi
        done <<< "$app_status"
        
        # Calculate health percentage
        local health_pct=0
        if [ $total_apps -gt 0 ]; then
            health_pct=$((healthy_apps * 100 / total_apps))
        fi
        
        print_info "ArgoCD status: $healthy_apps/$total_apps healthy ($health_pct%), $synced_apps/$total_apps synced"
        
        # Accept 80% healthy as success
        if [ $health_pct -ge 80 ] && [ $synced_apps -ge $((total_apps * 70 / 100)) ]; then
            print_success "ArgoCD applications sufficiently healthy ($health_pct% healthy)"
            return 0
        fi
        
        # Sync unhealthy apps (limit to first 5 to avoid overwhelming)
        local sync_count=0
        print_info "Syncing unhealthy applications:"
        for app in "${unhealthy_apps[@]}"; do
            [ $sync_count -ge 5 ] && break
            print_info "  Syncing: $app"
            if [ -n "$app" ]; then
                print_info "  Syncing: $app"
                
                # Check if app has comparison errors first
                local app_error=$(kubectl get application "$app" -n argocd -o jsonpath='{.status.conditions[?(@.type=="ComparisonError")].message}' 2>/dev/null || echo "")
                
                if [[ "$app_error" == *"cannot reference a different revision"* ]]; then
                    print_info "    Fixing revision conflict for $app before sync"
                    kubectl patch application "$app" -n argocd --type merge -p '{"spec":{"sources":[{"targetRevision":"HEAD"},{"targetRevision":"HEAD"}]}}' 2>/dev/null || true
                    sleep 5
                fi
                
                # Try ArgoCD CLI sync with longer timeout
                argocd app sync "$app" --timeout 120 --retry-limit 3 2>/dev/null || {
                    print_warning "    ArgoCD CLI sync failed for $app, using kubectl patch with force sync"
                    kubectl patch application "$app" -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD","prune":true,"syncOptions":["CreateNamespace=true","PrunePropagationPolicy=foreground"]}}}' 2>/dev/null || true
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

# Export additional environment variables for tools
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

update_workshop_var "KEYCLOAKIDPPASSWORD" "$KEYCLOAKIDPPASSWORD"
update_workshop_var "BACKSTAGEURL" "$BACKSTAGEURL"
update_workshop_var "GITLABPW" "$GITLABPW"
update_workshop_var "ARGOCDPW" "$ARGOCDPW"
update_workshop_var "ARGOCDURL" "$ARGOCDURL"
update_workshop_var "ARGOWFURL" "$ARGOWFURL"
update_workshop_var "ARGOCD_URL" "$ARGOCD_URL"
update_workshop_var "ARGOCD_TOKEN" "$ARGOCD_TOKEN"
update_workshop_var "GIT_HOSTNAME" "$GIT_HOSTNAME"
update_workshop_var "GIT_PASSWORD" "$GIT_PASSWORD"

print_success "ArgoCD and GitLab setup completed successfully."

print_header "Access Information"
print_info "You can connect to Argo CD UI and check everything is ok"
echo -e "${CYAN}ArgoCD URL:${BOLD} https://$DOMAIN_NAME/argocd${NC}"
echo -e "${CYAN}   Login:${BOLD} admin${NC}"
echo -e "${CYAN}   Password:${BOLD} $IDE_PASSWORD${NC}"

if [ -n "$GRAFANAURL" ]; then
    echo -e "${CYAN}Grafana URL:${BOLD} $GRAFANAURL${NC}"
fi

print_info "Next step: Run 2-bootstrap-accounts.sh to bootstrap management and spoke accounts."
