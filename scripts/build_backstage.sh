#!/bin/bash
set -ex

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Use a single variable for app name, repository, service, and cluster
APP_NAME="backstage"

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

echo "Building and pushing Docker image to ECR in region $AWS_REGION"

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build the Docker image
docker build -t $APP_NAME -f "$DOCKERFILE_PATH" "$BUILD_CONTEXT"

# Tag the image
docker tag $APP_NAME:latest $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$APP_NAME:latest

# Push the image to ECR
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$APP_NAME:latest

echo "Image successfully pushed to $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$APP_NAME:latest"
