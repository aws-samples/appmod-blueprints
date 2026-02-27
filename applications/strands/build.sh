#!/bin/bash
set -e

# Build script for Strands agent Docker image
# Builds for AMD64 platform (compatible with AWS EKS, ECS, etc.)

IMAGE_NAME="${IMAGE_NAME:-strands-agent}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PLATFORM="${PLATFORM:-linux/amd64}"
COMMAND="${1:-build}"
NO_CACHE=""

# Check for clean flag
if [ "$1" = "clean" ] || [ "$2" = "clean" ]; then
    NO_CACHE="--no-cache"
    echo "🧹 Clean build enabled (no cache)"
    if [ "$1" = "clean" ]; then
        COMMAND="${2:-build}"
    fi
fi

echo "========================================="
echo "Building Strands Agent Docker Image"
echo "========================================="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Platform: ${PLATFORM}"
echo "Command: ${COMMAND}"
echo "========================================="

# Build the image
if [ "$COMMAND" = "build" ] || [ "$COMMAND" = "push" ]; then
    echo ""
    echo "Building Docker image..."
    docker build \
        --platform "${PLATFORM}" \
        ${NO_CACHE} \
        -t "${IMAGE_NAME}:${IMAGE_TAG}" \
        -f Dockerfile \
        .
    
    echo ""
    echo "Build completed successfully!"
fi

# Push to ECR
if [ "$COMMAND" = "push" ]; then
    echo ""
    echo "========================================="
    echo "Pushing to Amazon ECR"
    echo "========================================="
    
    # Check for required environment variables
    if [ -z "$AWS_ACCOUNT_ID" ]; then
        echo "Getting AWS Account ID..."
        AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)
    fi
    
    if [ -z "$AWS_REGION" ]; then
        AWS_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
        echo "Using AWS Region: ${AWS_REGION}"
    fi
    
    ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${IMAGE_NAME}"
    
    echo "ECR Repository: ${ECR_REPO}"
    echo ""
    
    # Authenticate to ECR
    echo "Authenticating to ECR..."
    aws ecr get-login-password --region "${AWS_REGION}" | \
        docker login --username AWS --password-stdin \
        "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
    
    # Tag the image
    echo ""
    echo "Tagging image..."
    docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${ECR_REPO}:${IMAGE_TAG}"
    
    # Push the image
    echo ""
    echo "Pushing image to ECR..."
    
    # Try to create repository first (fallback for accounts without auto-creation)
    echo "Ensuring ECR repository exists..."
    if aws ecr describe-repositories --repository-names "${IMAGE_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1; then
        echo "Repository '${IMAGE_NAME}' already exists"
    else
        echo "Creating repository '${IMAGE_NAME}'..."
        aws ecr create-repository \
            --repository-name "${IMAGE_NAME}" \
            --region "${AWS_REGION}" \
            --image-scanning-configuration scanOnPush=true \
            --encryption-configuration encryptionType=AES256 || {
            echo "Note: Repository creation failed, but will try push anyway (ECR may auto-create)"
        }
    fi
    
    echo ""
    echo "Pushing image..."
    docker push "${ECR_REPO}:${IMAGE_TAG}"
    
    echo ""
    echo "========================================="
    echo "Push completed successfully!"
    echo "========================================="
    echo "Image: ${ECR_REPO}:${IMAGE_TAG}"
    echo ""
    echo "To use in Kubernetes:"
    echo "  image: ${ECR_REPO}:${IMAGE_TAG}"
    echo "========================================="
    exit 0
fi

# Show usage instructions
echo ""
echo "========================================="
echo "Build completed successfully!"
echo "========================================="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "To run locally:"
echo "  docker run -p 8083:8083 \\"
echo "    -e AWS_REGION=us-west-2 \\"
echo "    -e AWS_ACCESS_KEY_ID=\$AWS_ACCESS_KEY_ID \\"
echo "    -e AWS_SECRET_ACCESS_KEY=\$AWS_SECRET_ACCESS_KEY \\"
echo "    ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "To push to ECR (auto-creates repository):"
echo "  ./build.sh push"
echo ""
echo "To do a clean build (no cache):"
echo "  ./build.sh clean"
echo "  ./build.sh clean push"
echo ""
echo "Or with custom settings:"
echo "  IMAGE_NAME=my-agent IMAGE_TAG=v1.0.0 AWS_REGION=us-east-1 ./build.sh push"
echo "========================================="
