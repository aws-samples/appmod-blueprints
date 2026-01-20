#!/bin/bash
# Build and push optimized Ray GPU image to ECR

set -e

REGION=${AWS_REGION:-us-west-2}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
RESOURCE_PREFIX=${RESOURCE_PREFIX:-peeks}
REPO_NAME="${RESOURCE_PREFIX}-ray-vllm-custom"
IMAGE_TAG="latest"

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"

echo "Building optimized Ray GPU image..."
docker build -f Dockerfile.ray-gpu-optimized -t ${REPO_NAME}:${IMAGE_TAG} .

echo "Creating ECR repository if not exists..."
aws ecr describe-repositories --repository-names ${REPO_NAME} --region ${REGION} 2>/dev/null || \
  aws ecr create-repository --repository-name ${REPO_NAME} --region ${REGION}

echo "Logging into ECR..."
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ECR_URI}

echo "Tagging image..."
docker tag ${REPO_NAME}:${IMAGE_TAG} ${ECR_URI}:${IMAGE_TAG}

echo "Pushing to ECR..."
docker push ${ECR_URI}:${IMAGE_TAG}

echo "✅ Image pushed: ${ECR_URI}:${IMAGE_TAG}"
echo "Update RayService to use: ${ECR_URI}:latest"
