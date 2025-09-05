#!/bin/bash

#############################################################################
# Create Spoke EKS Clusters
#############################################################################
#
# DESCRIPTION:
#   This script creates the spoke EKS clusters in different regions. It:
#   1. Validates prerequisites and environment variables
#   2. Configures spoke cluster accounts in ArgoCD for ACK controller
#   3. Updates cluster definitions with management account ID and Git URLs
#   4. Enables and configures the peeks spoke clusters
#   5. Syncs the clusters application in ArgoCD
#   6. Creates the EKS clusters using KRO
#
# USAGE:
#   ./3-create-spoke-clusters.sh
#
# PREREQUISITES:
#   - Management and spoke accounts must be bootstrapped (run 2-bootstrap-accounts.sh first)
#   - ArgoCD must be configured and accessible
#   - Environment variables must be set:
#     - MGMT_ACCOUNT_ID: AWS Management account ID
#     - WORKSPACE_PATH: Path to the workspace directory
#     - WORKING_REPO: Name of the working repository
#     - GITLAB_URL: URL of the GitLab instance
#     - GIT_USERNAME: Git username for authentication
#     - WORKSHOP_GIT_BRANCH: Git branch to use
#
# SEQUENCE:
#   This is the fourth script (3) in the setup sequence.
#   Run after 2-bootstrap-accounts.sh and before 4-deploy-argo-rollouts-demo.sh
#
#############################################################################

set -e  # Exit on any error
#set -x

# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

# Validation function
validate_prerequisites() {
    print_step "Validating prerequisites"
    
    # Check required environment variables
    local required_vars=("MGMT_ACCOUNT_ID" "WORKSPACE_PATH" "WORKING_REPO" "GITLAB_URL" "GIT_USERNAME" "WORKSHOP_GIT_BRANCH")
    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            print_error "Required environment variable $var is not set"
            print_info "Please set all required variables:"
            print_info "  export MGMT_ACCOUNT_ID=\$(aws sts get-caller-identity --query Account --output text)"
            print_info "  export WORKSPACE_PATH=/home/ec2-user/environment"
            print_info "  export WORKING_REPO=platform-on-eks-workshop"
            print_info "  export GITLAB_URL=https://your-gitlab-url"
            print_info "  export GIT_USERNAME=your-username"
            print_info "  export WORKSHOP_GIT_BRANCH=your-branch"
            exit 1
        fi
    done
    
    # Check if workspace directory exists
    if [ ! -d "$WORKSPACE_PATH/$WORKING_REPO" ]; then
        print_error "Workspace directory $WORKSPACE_PATH/$WORKING_REPO does not exist"
        exit 1
    fi
    
    # Check if kubectl is available and connected
    if ! kubectl cluster-info >/dev/null 2>&1; then
        print_error "kubectl is not configured or cluster is not accessible"
        exit 1
    fi
    
    print_success "Prerequisites validation passed"
}

print_header "Creating Spoke EKS Clusters"

# Validate prerequisites first
validate_prerequisites

print_step "Configuring spoke cluster accounts in Argo CD application for ACK controller"
# Replace any existing account ID values (including MANAGEMENT_ACCOUNT_ID placeholder) with the actual management account ID
sed -i 's/: "[0-9]*"/: "'"$MGMT_ACCOUNT_ID"'"/g; s/MANAGEMENT_ACCOUNT_ID/'"$MGMT_ACCOUNT_ID"'/g' "$WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml"

print_step "Activating the account numbers"
sed -i 's/# \(cluster-dev: "[0-9]*"\)/\1/g; s/# \(cluster-prod: "[0-9]*"\)/\1/g' $WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml

print_info "Multi-acct values.yaml file updated"
if command -v code-server >/dev/null 2>&1; then
    print_info "Opening multi-acct values.yaml file for review"
    /usr/lib/code-server/bin/code-server $WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml
fi

print_step "Committing changes for namespaces and resources"
cd $WORKSPACE_PATH/$WORKING_REPO/
git status
git add .
if git diff --staged --quiet; then
    print_info "No changes to commit for multi-acct configuration"
else
    git commit -m "add namespaces and resources for clusters"
    if ! git push origin $WORKSHOP_GIT_BRANCH:main; then
        print_warning "Git push failed, but continuing with local changes..."
    fi
fi

print_step "Syncing the multi-acct application"
# Hard refresh first to detect new commits
kubectl patch application multi-acct-peeks-hub-cluster -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"info":[{"name":"Reason","value":"Hard refresh"}]}}'
sleep 5

# Force sync to HEAD
kubectl patch application multi-acct-peeks-hub-cluster -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"syncStrategy":{"hook":{}}}}}'
sleep 5

print_step "Waiting for the multi-acct application to be synced and healthy"
# Wait for sync with timeout, but check status manually
for i in {1..12}; do
    SYNC_STATUS=$(kubectl get application multi-acct-peeks-hub-cluster -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "Unknown")
    HEALTH_STATUS=$(kubectl get application multi-acct-peeks-hub-cluster -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null || echo "Unknown")
    
    if [ "$SYNC_STATUS" = "Synced" ] && [ "$HEALTH_STATUS" = "Healthy" ]; then
        print_success "Multi-acct application is synced and healthy"
        break
    fi
    
    print_info "Attempt $i/12: Sync=$SYNC_STATUS, Health=$HEALTH_STATUS"
    sleep 15
done

# Check final status
FINAL_SYNC=$(kubectl get application multi-acct-peeks-hub-cluster -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "Unknown")
if [ "$FINAL_SYNC" != "Synced" ]; then
    print_warning "Application not fully synced ($FINAL_SYNC), but continuing..."
fi

print_step "Updating cluster definitions with Management account ID and Git URLs"
# Replace specific patterns in kro-clusters values.yaml - works with any existing values
sed -i \
  -e 's/managementAccountId: "[^"]*"/managementAccountId: "'"$MGMT_ACCOUNT_ID"'"/g' \
  -e 's/accountId: "[^"]*"/accountId: "'"$MGMT_ACCOUNT_ID"'"/g' \
  -e 's|addonsRepoUrl: "[^"]*"|addonsRepoUrl: "'"$GITLAB_URL"'/'"$GIT_USERNAME"'/'"$WORKING_REPO"'.git"|g' \
  -e 's|fleetRepoUrl: "[^"]*"|fleetRepoUrl: "'"$GITLAB_URL"'/'"$GIT_USERNAME"'/'"$WORKING_REPO"'.git"|g' \
  -e 's|platformRepoUrl: "[^"]*"|platformRepoUrl: "'"$GITLAB_URL"'/'"$GIT_USERNAME"'/'"$WORKING_REPO"'.git"|g' \
  -e 's|workloadRepoUrl: "[^"]*"|workloadRepoUrl: "'"$GITLAB_URL"'/'"$GIT_USERNAME"'/'"$WORKING_REPO"'.git"|g' \
  "$WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml"

print_step "Enabling fleet spoke clusters"
sed -i '
# First uncomment the section headers
s/^  # cluster-dev:/  cluster-dev:/g
s/^  # cluster-prod:/  cluster-prod:/g

# Uncomment content between cluster-dev and its END MARKER
/^  cluster-dev:/,/^  # #END MARKER FOR SED/ {
  /^  # #END MARKER FOR SED/!s/^  #/  /g
}
# Uncomment content between cluster-prod and its END MARKER (if it exists)
/^  cluster-prod:/,/^  # #END MARKER FOR SED/ {
  /^  # #END MARKER FOR SED/!s/^  #/  /g
}' $WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml

print_info "Cluster values.yaml file updated"
if command -v code-server >/dev/null 2>&1; then
    print_info "Opening cluster values.yaml file for review"
    /usr/lib/code-server/bin/code-server $WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml
fi

print_step "Committing changes to Git repository"
cd $WORKSPACE_PATH/$WORKING_REPO/
git status
git add .
if git diff --staged --quiet; then
    print_info "No changes to commit for cluster definitions"
else
    git commit -m "add clusters definitions"
    if ! git push origin $WORKSHOP_GIT_BRANCH:main; then
        print_warning "Git push failed, but continuing with local changes..."
    fi
fi

sleep 10

print_step "Syncing clusters application in ArgoCD"
# Hard refresh first
kubectl patch application clusters -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"info":[{"name":"Reason","value":"Hard refresh"}]}}'
sleep 5

# Force sync
kubectl patch application clusters -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"syncStrategy":{"hook":{}}}}}'

# Wait with manual status checking
for i in {1..8}; do
    CLUSTERS_SYNC=$(kubectl get application clusters -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "Unknown")
    
    if [ "$CLUSTERS_SYNC" = "Synced" ]; then
        print_success "Clusters application is synced"
        break
    fi
    
    print_info "Attempt $i/8: Clusters sync=$CLUSTERS_SYNC"
    sleep 15
done

print_info "Checking EKS cluster creation status"
kubectl get EksClusterwithvpcs -A 2>/dev/null || print_info "No EKS clusters found yet, they may still be creating..."

print_success "Spoke EKS clusters creation initiated."

print_info "Wait for all clusters to be created, monitor kro and ACK logs:"
print_info "  kubectl get EksClusterwithvpcs -A -w"
print_info "  kubectl logs -n kro-system -l app.kubernetes.io/name=kro -f"
print_info "  kubectl logs -n ack-system deployment/eks-chart -f"

print_info "Next step: Run 4-deploy-argo-rollouts-demo.sh to deploy the Argo Rollouts demo application."
