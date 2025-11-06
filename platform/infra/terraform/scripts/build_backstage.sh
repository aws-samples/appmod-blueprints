#!/bin/bash
set -e

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"


# Use a single variable for app name, repository, service, and cluster
APP_NAME="${RESOURCE_PREFIX}-backstage"

# Check if APP_PATH was provided as the first parameter
APP_PATH="$1"
if [ -n "$APP_PATH" ]; then
    # APP_PATH provided, use Dockerfile there
    DOCKERFILE_PATH="$APP_PATH/Dockerfile"
    BUILD_CONTEXT="$APP_PATH"
    if [ ! -f "$DOCKERFILE_PATH" ]; then
        echo "Error: Dockerfile not found at $DOCKERFILE_PATH"
        exit 1
    fi
    echo "Using Dockerfile at $DOCKERFILE_PATH with context $BUILD_CONTEXT"
else
    # No APP_PATH provided, use script directory
    DOCKERFILE_PATH="$SCRIPT_DIR/Dockerfile"
    BUILD_CONTEXT="$SCRIPT_DIR"
    echo "Using default Dockerfile at $DOCKERFILE_PATH"
fi

echo "Building and pushing multi-arch Docker image to ECR in region $AWS_REGION"

# Create ECR repository if it doesn't exist
if ! aws ecr describe-repositories --repository-names $APP_NAME --region $AWS_REGION >/dev/null 2>&1; then
    echo "Creating ECR repository: $APP_NAME"
    aws ecr create-repository --repository-name $APP_NAME --region $AWS_REGION
else
    echo "ECR repository $APP_NAME already exists"
fi

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Create buildx builder if it doesn't exist
if ! docker buildx ls | grep -q multiarch; then
    echo "Creating multi-arch builder"
    docker buildx create --name multiarch --use --bootstrap
else
    echo "Using existing multi-arch builder"
    docker buildx use multiarch
fi

# Build and push multi-arch image (amd64 and arm64)
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$APP_NAME:latest \
    -f "$DOCKERFILE_PATH" \
    "$BUILD_CONTEXT" \
    --push

echo "Multi-arch image successfully pushed to $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$APP_NAME:latest"
echo "Supported architectures: linux/amd64, linux/arm64"
