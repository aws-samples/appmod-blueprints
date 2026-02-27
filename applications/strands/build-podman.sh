#!/bin/bash
set -e

# Build script for Strands agent using Podman
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
echo "Building Strands Agent with Podman"
echo "========================================="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Platform: ${PLATFORM}"
echo "Command: ${COMMAND}"
echo "========================================="

# Check if podman is installed
if ! command -v podman &> /dev/null; then
    echo "ERROR: podman is not installed"
    echo "Install podman: https://podman.io/getting-started/installation"
    exit 1
fi

# Build the image
if [ "$COMMAND" = "build" ] || [ "$COMMAND" = "push" ]; then
    # Check podman version
    PODMAN_VERSION=$(podman --version | awk '{print $3}')
    echo "Podman version: ${PODMAN_VERSION}"
    
    echo ""
    echo "Building image for ${PLATFORM}..."
    podman build \
        --platform "${PLATFORM}" \
        --format docker \
        ${NO_CACHE} \
        -t "${IMAGE_NAME}:${IMAGE_TAG}" \
        -f Dockerfile \
        .
    
    # Verify the built image
    echo ""
    echo "Verifying image architecture..."
    ARCH=$(podman inspect "${IMAGE_NAME}:${IMAGE_TAG}" --format '{{.Architecture}}')
    OS=$(podman inspect "${IMAGE_NAME}:${IMAGE_TAG}" --format '{{.Os}}')
    echo "Built image architecture: ${OS}/${ARCH}"
    
    if [ "${ARCH}" != "amd64" ]; then
        echo "WARNING: Image was built for ${ARCH}, expected amd64"
        echo "This may cause issues when deploying to AWS (x86_64 instances)"
    fi
    
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
    
    # Authenticate to ECR with Podman
    echo "Authenticating to ECR..."
    aws ecr get-login-password --region "${AWS_REGION}" | \
        podman login --username AWS --password-stdin \
        "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
    
    # Tag the image
    echo ""
    echo "Tagging image..."
    podman tag "${IMAGE_NAME}:${IMAGE_TAG}" "${ECR_REPO}:${IMAGE_TAG}"
    
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
    podman push "${ECR_REPO}:${IMAGE_TAG}"
    
    echo ""
    echo "========================================="
    echo "Push completed successfully!"
    echo "========================================="
    echo "Image: ${ECR_REPO}:${IMAGE_TAG}"
    echo "Architecture: ${OS}/${ARCH}"
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
echo "Architecture: ${OS}/${ARCH}"
echo ""
echo "To run locally with podman:"
echo "  podman run -p 8083:8083 \\"
echo "    -e AWS_REGION=us-west-2 \\"
echo "    -e AWS_ACCESS_KEY_ID=\$AWS_ACCESS_KEY_ID \\"
echo "    -e AWS_SECRET_ACCESS_KEY=\$AWS_SECRET_ACCESS_KEY \\"
echo "    ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "To test the container:"
echo "  podman run -d --name strands-test -p 8083:8083 \\"
echo "    -e AWS_REGION=us-west-2 ${IMAGE_NAME}:${IMAGE_TAG}"
echo "  curl http://localhost:8083/health"
echo "  podman stop strands-test && podman rm strands-test"
echo ""
echo "To push to ECR (auto-creates repository):"
echo "  ./build-podman.sh push"
echo ""
echo "To do a clean build (no cache):"
echo "  ./build-podman.sh clean"
echo "  ./build-podman.sh clean push"
echo ""
echo "Or with custom settings:"
echo "  IMAGE_NAME=my-agent IMAGE_TAG=v1.0.0 AWS_REGION=us-east-1 ./build-podman.sh push"
echo ""
echo "To save image as tar (for transfer):"
echo "  podman save -o ${IMAGE_NAME}.tar ${IMAGE_NAME}:${IMAGE_TAG}"
echo "========================================="
