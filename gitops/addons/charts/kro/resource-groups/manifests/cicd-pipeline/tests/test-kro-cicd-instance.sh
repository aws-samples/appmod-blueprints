#!/bin/bash

# Test script for Kro CI/CD Pipeline instance deployment and validation
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
RGD_FILE="cicd-pipeline.yaml"
TEST_INSTANCE_FILE="tests/test-cicd-pipeline-instance.yaml"
TEST_NAMESPACE="test-cicd-pipeline"

echo -e "${BLUE}[INFO]${NC} Kro CI/CD Pipeline Instance Test"
echo -e "${BLUE}[INFO]${NC} RGD file: $RGD_FILE"
echo -e "${BLUE}[INFO]${NC} Test instance file: $TEST_INSTANCE_FILE"
echo -e "${BLUE}[INFO]${NC} Test namespace: $TEST_NAMESPACE"

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check resource status and readiness
check_resource_status() {
    local resource_type="$1"
    local resource_name="$2"
    local namespace="$3"
    local timeout="${4:-30}"
    
    echo -e "${BLUE}[INFO]${NC} Checking $resource_type/$resource_name status..."
    
    # Check if resource exists
    if [ "$namespace" = "cluster-wide" ]; then
        if ! kubectl get "$resource_type" "$resource_name" >/dev/null 2>&1; then
            echo -e "${RED}[ERROR]${NC} ✗ $resource_type/$resource_name not found"
            return 1
        fi
    else
        if ! kubectl get "$resource_type" "$resource_name" -n "$namespace" >/dev/null 2>&1; then
            echo -e "${RED}[ERROR]${NC} ✗ $resource_type/$resource_name not found in namespace $namespace"
            return 1
        fi
    fi
    
    # Check resource-specific status conditions
    case "$resource_type" in
        "repository")
            # ACK ECR Repository - check if status shows ready
            local status
            if [ "$namespace" = "cluster-wide" ]; then
                status=$(kubectl get repository "$resource_name" -o jsonpath='{.status.conditions[?(@.type=="ACK.ResourceSynced")].status}' 2>/dev/null || echo "Unknown")
            else
                status=$(kubectl get repository "$resource_name" -n "$namespace" -o jsonpath='{.status.conditions[?(@.type=="ACK.ResourceSynced")].status}' 2>/dev/null || echo "Unknown")
            fi
            if [ "$status" = "True" ]; then
                echo -e "${GREEN}[SUCCESS]${NC} ✓ $resource_type/$resource_name is synced and ready"
                return 0
            else
                echo -e "${YELLOW}[WARNING]${NC} ⚠ $resource_type/$resource_name status: $status"
                return 1
            fi
            ;;
        "policy.iam.services.k8s.aws"|"role.iam.services.k8s.aws")
            # ACK IAM resources - check if status shows ready
            local status
            if [ "$namespace" = "cluster-wide" ]; then
                status=$(kubectl get "$resource_type" "$resource_name" -o jsonpath='{.status.conditions[?(@.type=="ACK.ResourceSynced")].status}' 2>/dev/null || echo "Unknown")
            else
                status=$(kubectl get "$resource_type" "$resource_name" -n "$namespace" -o jsonpath='{.status.conditions[?(@.type=="ACK.ResourceSynced")].status}' 2>/dev/null || echo "Unknown")
            fi
            if [ "$status" = "True" ]; then
                echo -e "${GREEN}[SUCCESS]${NC} ✓ $resource_type/$resource_name is synced and ready"
                return 0
            else
                echo -e "${YELLOW}[WARNING]${NC} ⚠ $resource_type/$resource_name status: $status"
                return 1
            fi
            ;;
        "job")
            # Check if job completed successfully
            local status
            if [ "$namespace" = "cluster-wide" ]; then
                status=$(kubectl get job "$resource_name" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "Unknown")
            else
                status=$(kubectl get job "$resource_name" -n "$namespace" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "Unknown")
            fi
            if [ "$status" = "True" ]; then
                echo -e "${GREEN}[SUCCESS]${NC} ✓ $resource_type/$resource_name completed successfully"
                return 0
            else
                echo -e "${YELLOW}[WARNING]${NC} ⚠ $resource_type/$resource_name status: $status"
                return 1
            fi
            ;;
        "workflow")
            # Check if workflow succeeded
            local phase
            if [ "$namespace" = "cluster-wide" ]; then
                phase=$(kubectl get workflow "$resource_name" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
            else
                phase=$(kubectl get workflow "$resource_name" -n "$namespace" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
            fi
            if [ "$phase" = "Succeeded" ]; then
                echo -e "${GREEN}[SUCCESS]${NC} ✓ $resource_type/$resource_name succeeded"
                return 0
            elif [ "$phase" = "Failed" ]; then
                echo -e "${RED}[ERROR]${NC} ✗ $resource_type/$resource_name failed"
                return 1
            else
                echo -e "${YELLOW}[WARNING]${NC} ⚠ $resource_type/$resource_name phase: $phase"
                return 1
            fi
            ;;
        "cicdpipeline")
            # Check CICDPipeline instance status
            local status
            if [ "$namespace" = "cluster-wide" ]; then
                status=$(kubectl get cicdpipeline "$resource_name" -o jsonpath='{.status.conditions[?(@.type=="InstanceSynced")].status}' 2>/dev/null || echo "Unknown")
            else
                status=$(kubectl get cicdpipeline "$resource_name" -n "$namespace" -o jsonpath='{.status.conditions[?(@.type=="InstanceSynced")].status}' 2>/dev/null || echo "Unknown")
            fi
            if [ "$status" = "True" ]; then
                echo -e "${GREEN}[SUCCESS]${NC} ✓ $resource_type/$resource_name is synced and ready"
                return 0
            else
                echo -e "${YELLOW}[WARNING]${NC} ⚠ $resource_type/$resource_name status: $status"
                return 1
            fi
            ;;
        *)
            # For other resources, just check existence
            echo -e "${GREEN}[SUCCESS]${NC} ✓ $resource_type/$resource_name exists"
            return 0
            ;;
    esac
}

# Function to wait for resource to be ready
wait_for_resource() {
    local resource_type="$1"
    local resource_name="$2"
    local namespace="$3"
    local timeout="${4:-60}"
    local interval=5
    local elapsed=0
    
    echo -e "${BLUE}[INFO]${NC} Waiting for $resource_type/$resource_name to be ready (timeout: ${timeout}s)..."
    
    while [ $elapsed -lt $timeout ]; do
        if check_resource_status "$resource_type" "$resource_name" "$namespace" >/dev/null 2>&1; then
            echo -e "${GREEN}[SUCCESS]${NC} ✓ $resource_type/$resource_name is ready after ${elapsed}s"
            return 0
        fi
        
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -e "${BLUE}[INFO]${NC} Still waiting... (${elapsed}s/${timeout}s)"
    done
    
    echo -e "${RED}[ERROR]${NC} ✗ $resource_type/$resource_name not ready after ${timeout}s"
    return 1
}

# Check prerequisites
echo -e "${BLUE}[INFO]${NC} Checking prerequisites..."

if ! command_exists kubectl; then
    echo -e "${RED}[ERROR]${NC} kubectl is not installed or not in PATH"
    exit 1
fi

# Check if we can connect to the cluster
if ! kubectl cluster-info >/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} Cannot connect to Kubernetes cluster"
    exit 1
fi

echo -e "${GREEN}[SUCCESS]${NC} Prerequisites check passed"

# Step 1: Apply the RGD if not already applied
echo -e "${BLUE}[INFO]${NC} Step 1: Checking if RGD is applied..."

if kubectl get resourcegraphdefinition cicdpipeline.kro.run >/dev/null 2>&1; then
    echo -e "${GREEN}[SUCCESS]${NC} RGD already exists in cluster"
else
    echo -e "${YELLOW}[INFO]${NC} Applying RGD to cluster..."
    kubectl apply -f "$RGD_FILE"
    echo -e "${GREEN}[SUCCESS]${NC} RGD applied successfully"
fi

# Step 2: Create test namespace
echo -e "${BLUE}[INFO]${NC} Step 2: Creating test namespace..."

if kubectl get namespace "$TEST_NAMESPACE" >/dev/null 2>&1; then
    echo -e "${YELLOW}[INFO]${NC} Test namespace already exists"
else
    kubectl create namespace "$TEST_NAMESPACE"
    echo -e "${GREEN}[SUCCESS]${NC} Test namespace created"
fi

# Step 3: Apply the test instance
echo -e "${BLUE}[INFO]${NC} Step 3: Applying test CICDPipeline instance..."

kubectl apply -f "$TEST_INSTANCE_FILE"
echo -e "${GREEN}[SUCCESS]${NC} Test instance applied"

# Step 4: Wait for initial resource creation
echo -e "${BLUE}[INFO]${NC} Step 4: Waiting for initial resource creation..."
sleep 15

# Step 5: Comprehensive resource status validation
echo -e "${BLUE}[INFO]${NC} Step 5: Comprehensive resource status validation..."

# Initialize counters
TOTAL_RESOURCES=0
SUCCESSFUL_RESOURCES=0
FAILED_RESOURCES=0
FAILED_RESOURCES_LIST=()

# Function to check and count resource status
check_and_count() {
    local resource_type="$1"
    local resource_name="$2"
    local namespace="$3"
    
    TOTAL_RESOURCES=$((TOTAL_RESOURCES + 1))
    
    if check_resource_status "$resource_type" "$resource_name" "$namespace"; then
        SUCCESSFUL_RESOURCES=$((SUCCESSFUL_RESOURCES + 1))
    else
        FAILED_RESOURCES=$((FAILED_RESOURCES + 1))
        if [ "$namespace" = "cluster-wide" ]; then
            FAILED_RESOURCES_LIST+=("$resource_type/$resource_name")
        else
            FAILED_RESOURCES_LIST+=("$resource_type/$resource_name (namespace: $namespace)")
        fi
    fi
}

# Check CICDPipeline instance first
echo -e "${BLUE}[INFO]${NC} === Checking CICDPipeline Instance ==="
check_and_count "cicdpipeline" "test-cicd-pipeline" "default"

# Check namespace
echo -e "${BLUE}[INFO]${NC} === Checking Namespace ==="
check_and_count "namespace" "$TEST_NAMESPACE" "cluster-wide"

# Check AWS ACK Resources
echo -e "${BLUE}[INFO]${NC} === Checking AWS ACK Resources ==="

# ECR Repositories
echo -e "${BLUE}[INFO]${NC} Checking ECR repositories..."
wait_for_resource "repository" "test-cicd-pipeline-main-repo" "$TEST_NAMESPACE" 120
check_and_count "repository" "test-cicd-pipeline-main-repo" "$TEST_NAMESPACE"

wait_for_resource "repository" "test-cicd-pipeline-cache-repo" "$TEST_NAMESPACE" 120
check_and_count "repository" "test-cicd-pipeline-cache-repo" "$TEST_NAMESPACE"

# IAM Resources
echo -e "${BLUE}[INFO]${NC} Checking IAM resources..."
wait_for_resource "policy.iam.services.k8s.aws" "peeks-test-app-ecr-policy" "$TEST_NAMESPACE" 120
check_and_count "policy.iam.services.k8s.aws" "peeks-test-app-ecr-policy" "$TEST_NAMESPACE"

wait_for_resource "role.iam.services.k8s.aws" "peeks-test-app-role" "$TEST_NAMESPACE" 120
check_and_count "role.iam.services.k8s.aws" "peeks-test-app-role" "$TEST_NAMESPACE"

# Check Kubernetes Native Resources
echo -e "${BLUE}[INFO]${NC} === Checking Kubernetes Native Resources ==="

# ServiceAccount
check_and_count "serviceaccount" "test-cicd-pipeline-sa" "$TEST_NAMESPACE"

# ConfigMap
check_and_count "configmap" "test-cicd-pipeline-config" "$TEST_NAMESPACE"

# Secret
check_and_count "secret" "test-cicd-pipeline-docker-config" "$TEST_NAMESPACE"

# RBAC Resources
check_and_count "role" "test-cicd-pipeline-role" "$TEST_NAMESPACE"
check_and_count "rolebinding" "test-cicd-pipeline-rolebinding" "$TEST_NAMESPACE"

# CronJob
check_and_count "cronjob" "test-cicd-pipeline-ecr-refresh" "$TEST_NAMESPACE"

# Check Argo Workflows Resources
echo -e "${BLUE}[INFO]${NC} === Checking Argo Workflows Resources ==="

# WorkflowTemplates
if kubectl get workflowtemplate -n "$TEST_NAMESPACE" 2>/dev/null | grep -q "test-cicd-pipeline-provisioning-workflow"; then
    check_and_count "workflowtemplate" "test-cicd-pipeline-provisioning-workflow" "$TEST_NAMESPACE"
fi

# Setup workflows (may be created dynamically)
if kubectl get workflow -n "$TEST_NAMESPACE" 2>/dev/null | grep -q "test-cicd-pipeline-setup"; then
    for workflow in $(kubectl get workflow -n "$TEST_NAMESPACE" -o name 2>/dev/null | grep "test-cicd-pipeline-setup" | cut -d'/' -f2); do
        check_and_count "workflow" "$workflow" "$TEST_NAMESPACE"
    done
fi

# Check Argo Events Resources
echo -e "${BLUE}[INFO]${NC} === Checking Argo Events Resources ==="

# EventSource
if kubectl get eventsource -n "$TEST_NAMESPACE" 2>/dev/null | grep -q "test-cicd-pipeline-gitlab-eventsource"; then
    check_and_count "eventsource" "test-cicd-pipeline-gitlab-eventsource" "$TEST_NAMESPACE"
fi

# Sensor
if kubectl get sensor -n "$TEST_NAMESPACE" 2>/dev/null | grep -q "test-cicd-pipeline-gitlab-sensor"; then
    check_and_count "sensor" "test-cicd-pipeline-gitlab-sensor" "$TEST_NAMESPACE"
fi

# Step 6: Check Kro Instance Status and Display Resources
echo -e "${BLUE}[INFO]${NC} Step 6: Checking Kro Instance Status..."

# Check the CICDPipeline instance status in detail
echo -e "${BLUE}[INFO]${NC} CICDPipeline instance detailed status:"
if kubectl get cicdpipeline test-cicd-pipeline -n default >/dev/null 2>&1; then
    kubectl get cicdpipeline test-cicd-pipeline -n default -o yaml | grep -A 20 "status:" || echo "No status information available"
    
    # Check if Kro has finished processing
    kro_status=$(kubectl get cicdpipeline test-cicd-pipeline -n default -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
    if [ "$kro_status" = "True" ]; then
        echo -e "${GREEN}[SUCCESS]${NC} ✓ Kro has successfully processed the CICDPipeline instance"
    else
        echo -e "${YELLOW}[WARNING]${NC} ⚠ Kro processing status: $kro_status"
    fi
else
    echo -e "${RED}[ERROR]${NC} ✗ CICDPipeline instance not found"
fi

echo -e "${BLUE}[INFO]${NC} === Displaying all resources created by Kro ==="

echo -e "${BLUE}[INFO]${NC} Standard Kubernetes resources:"
kubectl get all -n "$TEST_NAMESPACE" 2>/dev/null || echo "No standard resources found"

echo -e "${BLUE}[INFO]${NC} ConfigMaps and Secrets:"
kubectl get configmap,secret -n "$TEST_NAMESPACE" 2>/dev/null || echo "No configmaps/secrets found"

echo -e "${BLUE}[INFO]${NC} RBAC resources:"
kubectl get role,rolebinding,serviceaccount -n "$TEST_NAMESPACE" 2>/dev/null || echo "No RBAC resources found"

echo -e "${BLUE}[INFO]${NC} AWS ACK resources:"
kubectl get repository,policy,role,podidentityassociation -n "$TEST_NAMESPACE" 2>/dev/null || echo "No ACK resources found"

echo -e "${BLUE}[INFO]${NC} Argo Workflows resources:"
kubectl get workflowtemplate,workflow -n "$TEST_NAMESPACE" 2>/dev/null || echo "No Argo Workflows resources found"

echo -e "${BLUE}[INFO]${NC} Argo Events resources:"
kubectl get eventsource,sensor -n "$TEST_NAMESPACE" 2>/dev/null || echo "No Argo Events resources found"

echo -e "${BLUE}[INFO]${NC} Ingress and Services:"
kubectl get ingress,service -n "$TEST_NAMESPACE" 2>/dev/null || echo "No ingress/services found"

# Show resources with Kro labels
echo -e "${BLUE}[INFO]${NC} Resources managed by Kro (with kro labels):"
kubectl get all,configmap,secret,role,rolebinding,serviceaccount,repository,policy,workflowtemplate,workflow,eventsource,sensor,ingress -n "$TEST_NAMESPACE" -l app.kubernetes.io/managed-by=kro 2>/dev/null || echo "No Kro-managed resources found with labels"

# Step 7: Final Status Summary
echo -e "${BLUE}[INFO]${NC} Step 7: Final Status Summary"
echo -e "${BLUE}[INFO]${NC} ================================"

echo -e "${BLUE}[INFO]${NC} Resource Status Summary:"
echo -e "${BLUE}[INFO]${NC} Total Resources Checked: $TOTAL_RESOURCES"
echo -e "${GREEN}[SUCCESS]${NC} Successful Resources: $SUCCESSFUL_RESOURCES"
echo -e "${RED}[ERROR]${NC} Failed Resources: $FAILED_RESOURCES"

# Display failed resources if any
if [ $FAILED_RESOURCES -gt 0 ]; then
    echo -e "${RED}[ERROR]${NC} Failed Resources Details:"
    for failed_resource in "${FAILED_RESOURCES_LIST[@]}"; do
        echo -e "${RED}[ERROR]${NC}   ✗ $failed_resource"
    done
fi

# Calculate success percentage
if [ $TOTAL_RESOURCES -gt 0 ]; then
    SUCCESS_PERCENTAGE=$((SUCCESSFUL_RESOURCES * 100 / TOTAL_RESOURCES))
    echo -e "${BLUE}[INFO]${NC} Success Rate: ${SUCCESS_PERCENTAGE}%"
else
    SUCCESS_PERCENTAGE=0
fi

# Final verdict
if [ $FAILED_RESOURCES -eq 0 ] && [ $SUCCESSFUL_RESOURCES -gt 0 ]; then
    echo -e "${GREEN}[SUCCESS]${NC} ✅ ALL RESOURCES CREATED AND READY!"
    echo -e "${GREEN}[SUCCESS]${NC} ✅ Kro RGD is working perfectly!"
    exit 0
elif [ $SUCCESS_PERCENTAGE -ge 80 ]; then
    echo -e "${YELLOW}[WARNING]${NC} ⚠ Most resources are ready, but some may still be initializing"
    echo -e "${YELLOW}[WARNING]${NC} ⚠ Consider waiting longer or checking logs for the failed resources listed above"
    if [ $FAILED_RESOURCES -gt 0 ]; then
        echo -e "${YELLOW}[WARNING]${NC} ⚠ You can check individual resource status with:"
        for failed_resource in "${FAILED_RESOURCES_LIST[@]}"; do
            resource_parts=(${failed_resource//\// })
            resource_type="${resource_parts[0]}"
            resource_name="${resource_parts[1]}"
            if [[ "$failed_resource" == *"namespace:"* ]]; then
                namespace=$(echo "$failed_resource" | sed -n 's/.*namespace: \([^)]*\).*/\1/p')
                echo -e "${YELLOW}[WARNING]${NC}   kubectl describe $resource_type $resource_name -n $namespace"
            else
                echo -e "${YELLOW}[WARNING]${NC}   kubectl describe $resource_type $resource_name"
            fi
        done
    fi
    exit 1
else
    echo -e "${RED}[ERROR]${NC} ✗ SIGNIFICANT ISSUES DETECTED"
    echo -e "${RED}[ERROR]${NC} ✗ Multiple resources failed or are not ready"
    if [ $FAILED_RESOURCES -gt 0 ]; then
        echo -e "${RED}[ERROR]${NC} ✗ Check the failed resources listed above for detailed error information"
    fi
    exit 2
fi

echo -e "${BLUE}[INFO]${NC} Test completed!"
echo -e "${BLUE}[INFO]${NC} To clean up: kubectl delete cicdpipeline test-cicd-pipeline -n default && kubectl delete namespace $TEST_NAMESPACE"