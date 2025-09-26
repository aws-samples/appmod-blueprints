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

# Source environment variables first
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        if [ -f "$file" ]; then
            source "$file"
        fi
    done
fi
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
GIT_ROOT_PATH=$(git rev-parse --show-toplevel)
source "${GIT_ROOT_PATH}/platform/infra/terraform/scripts/utils.sh"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

set -e
#set -x # debug

# Function to check if background build is still running
check_backstage_build_status() {
    if [ -n "$BACKSTAGE_BUILD_PID" ] && kill -0 $BACKSTAGE_BUILD_PID 2>/dev/null; then
        return 0  # Still running
    else
        return 1  # Finished or failed
    fi
}

check_backstage_ecr_repo() {
    if aws ecr describe-repositories --repository-names ${RESOURCE_PREFIX}-backstage --region $AWS_REGION 2>/dev/null; then
        print_info "Backstage ECR repository exist.. Assuming it has the backstage image, returning..."
        return 0
    fi

    return 1
}

start_backstage_build() {
    print_header "Starting Backstage build process"

    print_step "Creating Amazon Elastic Container Repository (Amazon ECR) for Backstage image"
    aws ecr create-repository --repository-name ${RESOURCE_PREFIX}-backstage --region $AWS_REGION

    print_step "Preparing Backstage for build"
    BACKSTAGE_PATH="${GIT_ROOT_PATH}/backstage"

    # Update yarn lockfile if needed (for new dependencies)
    print_info "Updating Backstage dependencies and lockfile..."
    cd "$BACKSTAGE_PATH"
    yarn install
    cd - > /dev/null

    print_info "Building Backstage image in background..."

    # Create a temporary log file for the background build
    BACKSTAGE_LOG="/tmp/backstage_build_$$.log"
    $SCRIPT_DIR/build_backstage.sh "$BACKSTAGE_PATH" > "$BACKSTAGE_LOG" 2>&1 &
    export BACKSTAGE_BUILD_PID=$!
    print_info "Backstage build started with PID: $BACKSTAGE_BUILD_PID (logs: $BACKSTAGE_LOG)"
}
