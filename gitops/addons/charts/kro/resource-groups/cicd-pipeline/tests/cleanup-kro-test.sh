#!/bin/bash

# Cleanup script for Kro CI/CD Pipeline test resources
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

TEST_NAMESPACE="test-cicd-pipeline"

echo -e "${BLUE}[INFO]${NC} Cleaning up Kro CI/CD Pipeline test resources"

# Function to delete ECR images
delete_ecr_images() {
    local repo_name="$1"
    echo -e "${BLUE}[INFO]${NC} Checking for images in ECR repository: $repo_name"
    
    # List images in the repository
    local images=$(aws ecr list-images --repository-name "$repo_name" --region us-west-2 --query 'imageIds[*]' --output json 2>/dev/null || echo "[]")
    
    if [ "$images" != "[]" ] && [ "$images" != "" ]; then
        echo -e "${YELLOW}[WARNING]${NC} Found images in repository $repo_name, deleting them..."
        aws ecr batch-delete-image --repository-name "$repo_name" --region us-west-2 --image-ids "$images" >/dev/null 2>&1 || true
        echo -e "${GREEN}[SUCCESS]${NC} Images deleted from repository $repo_name"
    else
        echo -e "${BLUE}[INFO]${NC} No images found in repository $repo_name"
    fi
}

# Clean up ECR images first to prevent finalizer issues
echo -e "${BLUE}[INFO]${NC} Cleaning up ECR images to prevent finalizer issues..."

# Get ECR repository names from the CICDPipeline status
if kubectl get cicdpipeline test-cicd-pipeline -n default >/dev/null 2>&1; then
    echo -e "${BLUE}[INFO]${NC} Getting ECR repository information from CICDPipeline..."
    
    # Extract repository names from the status
    main_repo_uri=$(kubectl get cicdpipeline test-cicd-pipeline -n default -o jsonpath='{.status.ecrMainRepositoryURI}' 2>/dev/null || echo "")
    cache_repo_uri=$(kubectl get cicdpipeline test-cicd-pipeline -n default -o jsonpath='{.status.ecrCacheRepositoryURI}' 2>/dev/null || echo "")
    
    if [ -n "$main_repo_uri" ]; then
        main_repo_name=$(echo "$main_repo_uri" | cut -d'/' -f2-)
        delete_ecr_images "$main_repo_name"
    fi
    
    if [ -n "$cache_repo_uri" ]; then
        cache_repo_name=$(echo "$cache_repo_uri" | cut -d'/' -f2-)
        delete_ecr_images "$cache_repo_name"
    fi
else
    # Fallback: try common repository names
    echo -e "${YELLOW}[WARNING]${NC} CICDPipeline not found, trying common repository names..."
    delete_ecr_images "peeks/test-app" || true
    delete_ecr_images "peeks/test-app/cache" || true
fi

# Delete the CICDPipeline instance
echo -e "${BLUE}[INFO]${NC} Deleting CICDPipeline instance..."
if kubectl get cicdpipeline test-cicd-pipeline -n default >/dev/null 2>&1; then
    kubectl delete cicdpipeline test-cicd-pipeline -n default
    echo -e "${GREEN}[SUCCESS]${NC} CICDPipeline instance deleted"
else
    echo -e "${YELLOW}[INFO]${NC} CICDPipeline instance not found"
fi

# Wait a moment for cleanup to propagate
echo -e "${BLUE}[INFO]${NC} Waiting for resources to be cleaned up..."
sleep 10

# Delete the test namespace (this should cascade delete most resources)
echo -e "${BLUE}[INFO]${NC} Deleting test namespace..."
if kubectl get namespace "$TEST_NAMESPACE" >/dev/null 2>&1; then
    kubectl delete namespace "$TEST_NAMESPACE" --timeout=120s
    echo -e "${GREEN}[SUCCESS]${NC} Test namespace deleted"
else
    echo -e "${YELLOW}[INFO]${NC} Test namespace not found"
fi

# Check for any remaining ACK resources that might not be namespace-scoped
echo -e "${BLUE}[INFO]${NC} Checking for remaining ACK resources..."

# Check for IAM resources (these might be cluster-scoped)
if kubectl get policy --all-namespaces 2>/dev/null | grep -q "test-cicd-pipeline"; then
    echo -e "${YELLOW}[WARNING]${NC} Found remaining IAM policies, attempting cleanup..."
    kubectl get policy --all-namespaces | grep "test-cicd-pipeline" | awk '{print $2 " -n " $1}' | xargs -r kubectl delete policy
fi

if kubectl get role --all-namespaces 2>/dev/null | grep -q "test-cicd-pipeline.*iam"; then
    echo -e "${YELLOW}[WARNING]${NC} Found remaining IAM roles, attempting cleanup..."
    kubectl get role --all-namespaces | grep "test-cicd-pipeline.*iam" | awk '{print $2 " -n " $1}' | xargs -r kubectl delete role
fi

echo -e "${GREEN}[SUCCESS]${NC} ✅ Cleanup completed!"
echo -e "${BLUE}[INFO]${NC} You can now run the test again with: ./test-kro-cicd-instance.sh"