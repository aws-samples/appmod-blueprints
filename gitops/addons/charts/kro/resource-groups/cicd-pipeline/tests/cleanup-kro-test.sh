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
    kubectl delete namespace "$TEST_NAMESPACE" --timeout=60s
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