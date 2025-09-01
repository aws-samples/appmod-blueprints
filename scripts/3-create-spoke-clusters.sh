#!/bin/bash

#############################################################################
# Create Spoke EKS Clusters
#############################################################################
#
# DESCRIPTION:
#   This script creates the spoke EKS clusters in different regions. It:
#   1. Validates prerequisites and environment variables
#   2. Creates ACK workload roles for cross-account access
#   3. Configures spoke cluster accounts in ArgoCD for ACK controller
#   4. Updates cluster definitions with management account ID and Git URLs
#   5. Enables and configures the peeks spoke clusters
#   6. Syncs the clusters application in ArgoCD
#   7. Creates the EKS clusters using KRO
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

# Create ACK workload roles
create_ack_workload_roles() {
    print_step "Creating ACK workload roles for cross-account access"
    
    if [ -f "$SCRIPT_DIR/create_ack_workload_roles.sh" ]; then
        print_info "Running ACK workload roles creation script"
        cd "$SCRIPT_DIR"
        MGMT_ACCOUNT_ID="$MGMT_ACCOUNT_ID" ./create_ack_workload_roles.sh
        if [ $? -eq 0 ]; then
            print_success "ACK workload roles created successfully"
        else
            print_warning "ACK workload roles creation failed, but continuing..."
        fi
    else
        print_warning "ACK workload roles script not found, skipping..."
    fi
}

print_header "Creating Spoke EKS Clusters"

# Validate prerequisites first
validate_prerequisites

# Create ACK workload roles
create_ack_workload_roles

print_step "Configuring spoke cluster accounts in Argo CD application for ACK controller"
sed -i 's/MANAGEMENT_ACCOUNT_ID/'"$MGMT_ACCOUNT_ID"'/g' "$WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml"

print_step "Activating the account numbers"
sed -i 's/# \(cluster-test: "[0-9]*"\)/\1/g; s/# \(cluster-pre-prod: "[0-9]*"\)/\1/g; s/# \(cluster-prod-eu: "[0-9]*"\)/\1/g; s/# \(cluster-prod-us: "[0-9]*"\)/\1/g' $WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml

print_info "Multi-acct values.yaml file updated"
if command -v code-server >/dev/null 2>&1; then
    print_info "Opening multi-acct values.yaml file for review"
    /usr/lib/code-server/bin/code-server $WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml
fi

print_step "Committing changes for namespaces and resources"
cd $WORKSPACE_PATH/$WORKING_REPO/
git status
git add .
git commit -m "add namespaces and resources for clusters"
git push origin $WORKSHOP_GIT_BRANCH:main

print_step "Syncing the cluster-workloads application"
kubectl patch application multi-acct-hub-cluster -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"syncStrategy":{"hook":{}}}}}'

print_step "Waiting for the multi-acct application to be synced and healthy"
kubectl wait --for=condition=Synced application/multi-acct-hub-cluster -n argocd --timeout=300s || print_warning "Sync timeout, but continuing..."
kubectl wait --for=condition=Healthy application/multi-acct-hub-cluster -n argocd --timeout=300s || print_warning "Health timeout, but continuing..."

print_step "Updating cluster definitions with Management account ID"
sed -i 's/MANAGEMENT_ACCOUNT_ID/'"$MGMT_ACCOUNT_ID"'/g' "$WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml"
sed -i 's|GITLAB_URL|'"$GITLAB_URL"'|g' "$WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml"
sed -i 's/GIT_USERNAME/'"$GIT_USERNAME"'/g' "$WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml"
sed -i 's/WORKING_REPO/'"$WORKING_REPO"'/g' "$WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml"

print_step "Enabling fleet spoke clusters"
sed -i '
# First uncomment the section headers
s/^  # cluster-test:/  cluster-test:/g
s/^  # cluster-pre-prod:/  cluster-pre-prod:/g
s/^  # cluster-prod-us:/  cluster-prod-us:/g
s/^  # cluster-prod-eu:/  cluster-prod-eu:/g

# Then uncomment the content under each section, but stop before workload-cluster1
/^  cluster-test:/,/^  cluster-pre-prod:/ {
  s/^  #/  /g
}
/^  cluster-pre-prod:/,/^  cluster-prod-us:/ {
  s/^  #/  /g
}
/^  cluster-prod-us:/,/^  cluster-prod-eu:/ {
  s/^  #/  /g
}
/^  cluster-prod-eu:/,/^  # workload-cluster1:/ {
  /^  # workload-cluster1:/!s/^  #/  /g
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
git commit -m "add clusters definitions"
git push origin $WORKSHOP_GIT_BRANCH:main

sleep 10

print_step "Syncing clusters application in ArgoCD"
kubectl patch application clusters -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"syncStrategy":{"hook":{}}}}}'
kubectl wait --for=condition=Synced application/clusters -n argocd --timeout=300s || print_warning "Clusters sync timeout, but continuing..."

print_info "Checking EKS cluster creation status"
kubectl get EksClusterwithvpcs -A 2>/dev/null || print_info "No EKS clusters found yet, they may still be creating..."

print_success "Spoke EKS clusters creation initiated."

print_info "Wait for all clusters to be created, monitor kro and ACK logs:"
print_info "  kubectl get EksClusterwithvpcs -A -w"
print_info "  kubectl logs -n kro-system -l app.kubernetes.io/name=kro -f"
print_info "  kubectl logs -n ack-system deployment/eks-chart -f"

print_info "Next step: Run 4-deploy-argo-rollouts-demo.sh to deploy the Argo Rollouts demo application."
