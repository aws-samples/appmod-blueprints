#!/bin/bash

#############################################################################
# Create Spoke EKS Clusters
#############################################################################
#
# DESCRIPTION:
#   This script creates the spoke EKS clusters in different regions. It:
#   1. Configures spoke cluster accounts in ArgoCD for ACK controller
#   2. Updates cluster definitions with management account ID and Git URLs
#   3. Enables and configures the peeks spoke clusters
#   4. Syncs the clusters application in ArgoCD
#   5. Creates the EKS clusters using KRO
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
#
# SEQUENCE:
#   This is the fourth script (3) in the setup sequence.
#   Run after 2-bootstrap-accounts.sh and before 4-deploy-argo-rollouts-demo.sh
#
#############################################################################

# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

print_header "Creating Spoke EKS Clusters"

print_step "Configuring spoke cluster accounts in Argo CD application for ACK controller"
sed -i 's/MANAGEMENT_ACCOUNT_ID/'"$MGMT_ACCOUNT_ID"'/g' "$WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml"

print_step "Activating the account numbers"
sed -i 's/# \(cluster-test: "[0-9]*"\)/\1/g; s/# \(cluster-pre-prod: "[0-9]*"\)/\1/g; s/# \(cluster-prod-eu: "[0-9]*"\)/\1/g; s/# \(cluster-prod-us: "[0-9]*"\)/\1/g' $WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml

print_info "Opening multi-acct values.yaml file for review"
/usr/lib/code-server/bin/code-server $WORKSPACE_PATH/$WORKING_REPO/gitops/addons/tenants/tenant1/default/addons/multi-acct/values.yaml

print_step "Committing changes for namespaces and resources"
cd $WORKSPACE_PATH/$WORKING_REPO/
git status
git add .
git commit -m "add namespaces and resources for clusters"
git push origin $WORKSHOP_GIT_BRANCH:main

print_step "Syncing the cluster-workloads application"
argocd app sync multi-acct-hub-cluster

print_step "Waiting for the rollouts-demo-kargo application to be synced and healthy"
argocd app wait multi-acct-hub-cluster --health --sync

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

print_info "Opening cluster values.yaml file for review"
/usr/lib/code-server/bin/code-server $WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml

print_step "Committing changes to Git repository"
cd $WORKSPACE_PATH/$WORKING_REPO/
git status
git add .
git commit -m "add clusters definitions"
git push origin $WORKSHOP_GIT_BRANCH:main

sleep 10

print_step "Syncing clusters application in ArgoCD"
argocd app sync clusters
argocd app wait clusters

print_info "Checking EKS cluster creation status"
kubectl get EksClusterwithvpcs -A

print_success "Spoke EKS clusters creation initiated."

print_info "Wait for all clusters to be created, monitor kro and ACK logs"

print_info "Next step: Run 4-deploy-argo-rollouts-demo.sh to deploy the Argo Rollouts demo application."
