#!/bin/bash

# Source environment variables first
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        if [ -f "$file" ]; then
            source "$file"
        fi
    done
fi

# Source the colors script
GIT_ROOT_PATH=$(git rev-parse --show-toplevel)
source "${GIT_ROOT_PATH}/platform/infra/terraform/scripts/utils.sh"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

set -e
#set -x # debug

# Function to check if background build is still running
check_backstage_build_status() {
    if [ -n "$BACKSTAGE_BUILD_PID" ] && kill -0 $BACKSTAGE_BUILD_PID 2>/dev/null; then
        return 2  # Still running
    else
        # Process finished, check log for success/failure
        if [ -f "$BACKSTAGE_LOG" ] && grep -q "Image successfully pushed" "$BACKSTAGE_LOG"; then
            return 0  # Success
        else
            return 1  # Failed
        fi
    fi
}

check_backstage_ecr_image() {
    if ! aws ecr describe-repositories --repository-names ${RESOURCE_PREFIX}-backstage --region $AWS_REGION > /dev/null 2>&1; then
        return 1
    fi

    if aws ecr describe-images --repository-name ${RESOURCE_PREFIX}-backstage --image-ids imageTag=latest --region $AWS_REGION > /dev/null 2>&1; then
        print_info "Backstage ECR image with latest tag exists, returning..."
        return 0
    fi

    return 1
}

start_backstage_build() {
    print_header "Starting Backstage build process"

    print_step "Creating Amazon Elastic Container Repository (Amazon ECR) for Backstage image"
    aws ecr create-repository --repository-name ${RESOURCE_PREFIX}-backstage --region $AWS_REGION > /dev/null 2>&1 || true

    print_step "Preparing Backstage for build"
    BACKSTAGE_PATH="${GIT_ROOT_PATH}/backstage"

    # Update yarn lockfile if needed (for new dependencies)
    # print_info "Updating Backstage dependencies and lockfile..."
    # cd "$BACKSTAGE_PATH"
    # yarn install
    # cd - > /dev/null

    print_info "Building Backstage image in background..."

    # Create a temporary log file for the background build
    BACKSTAGE_LOG="/tmp/backstage_build_$$.log"
    export BACKSTAGE_LOG
    $SCRIPT_DIR/build_backstage.sh "$BACKSTAGE_PATH" > "$BACKSTAGE_LOG" 2>&1 &
    export BACKSTAGE_BUILD_PID=$!
    print_info "Backstage build started with PID: $BACKSTAGE_BUILD_PID (logs: $BACKSTAGE_LOG)"
}
