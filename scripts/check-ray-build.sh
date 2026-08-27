#!/bin/bash

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/colors.sh"

# Get resource prefix from environment
RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
PROJECT_NAME="${RESOURCE_PREFIX}-ray-vllm-build"

print_info "Checking Ray+vLLM CodeBuild status..."

# Get the most recent build
BUILD_ID=$(aws codebuild list-builds-for-project \
    --project-name "$PROJECT_NAME" \
    --region "$AWS_REGION" \
    --query 'ids[0]' \
    --output text 2>/dev/null | head -1)

if [ -z "$BUILD_ID" ] || [ "$BUILD_ID" = "None" ]; then
    print_error "No builds found for project: $PROJECT_NAME"
    exit 1
fi

# Get build status (capture stderr separately)
BUILD_STATUS_OUTPUT=$(aws codebuild batch-get-builds \
    --ids "$BUILD_ID" \
    --region "$AWS_REGION" \
    --query 'builds[0].buildStatus' \
    --output text 2>&1)

BUILD_EXIT_CODE=$?

# Check if command succeeded
if [ $BUILD_EXIT_CODE -ne 0 ]; then
    print_error "AWS CLI error: $BUILD_STATUS_OUTPUT"
    exit 1
fi

BUILD_STATUS="$BUILD_STATUS_OUTPUT"

if [ -z "$BUILD_STATUS" ] || [ "$BUILD_STATUS" = "None" ]; then
    print_error "No build status returned for: $BUILD_ID"
    exit 1
fi

echo "  Build ID: $BUILD_ID"
echo "  Status: $BUILD_STATUS"

case "$BUILD_STATUS" in
    "SUCCEEDED")
        print_success "Ray+vLLM image build completed successfully"
        exit 0
        ;;
    "IN_PROGRESS")
        print_warning "Build is currently in progress"
        print_info "Run this command again to check status, or wait for completion"
        exit 0
        ;;
    "FAILED"|"FAULT"|"TIMED_OUT"|"STOPPED")
        print_error "Build failed with status: $BUILD_STATUS"
        print_info "Triggering retry..."
        ;;
    *)
        print_warning "Unknown build status: $BUILD_STATUS"
        exit 1
        ;;
esac

# Trigger new build
print_step "Starting new build..."
LAMBDA_NAME="${RESOURCE_PREFIX}-trigger-ray-vllm-build"

NEW_BUILD=$(aws lambda invoke \
    --function-name "$LAMBDA_NAME" \
    --region "$AWS_REGION" \
    --output json \
    /tmp/lambda-response.json 2>&1)

if [ $? -eq 0 ]; then
    print_success "New build triggered successfully"
    print_info "Run this command again to check the new build status"
else
    print_error "Failed to trigger new build"
    exit 1
fi
