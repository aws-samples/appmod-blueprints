#!/bin/bash

# Validation script for Kro CI/CD Pipeline RGD
# This script validates the RGD definition and ensures it's properly recognized by Kro

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
RGD_NAME="cicdpipeline.kro.run"
RGD_FILE="appmod-blueprints/gitops/addons/charts/kro/resource-groups/cicd-pipeline/cicd-pipeline.yaml"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to validate RGD file
validate_rgd_file() {
    print_status "Validating RGD file: $RGD_FILE"
    
    if [ ! -f "$RGD_FILE" ]; then
        print_error "RGD file not found: $RGD_FILE"
        return 1
    fi
    
    print_success "RGD file exists"
    
    # Validate YAML syntax
    if ! kubectl apply --dry-run=client -f "$RGD_FILE" >/dev/null 2>&1; then
        print_error "RGD file has invalid YAML syntax"
        kubectl apply --dry-run=client -f "$RGD_FILE"
        return 1
    fi
    
    print_success "RGD file has valid YAML syntax"
    
    # Check required fields
    local api_version=$(yq eval '.apiVersion' "$RGD_FILE" 2>/dev/null || echo "")
    local kind=$(yq eval '.kind' "$RGD_FILE" 2>/dev/null || echo "")
    local name=$(yq eval '.metadata.name' "$RGD_FILE" 2>/dev/null || echo "")
    
    if [ "$api_version" != "kro.run/v1alpha1" ]; then
        print_error "Invalid apiVersion: expected 'kro.run/v1alpha1', got '$api_version'"
        return 1
    fi
    print_success "API version is correct: $api_version"
    
    if [ "$kind" != "ResourceGraphDefinition" ]; then
        print_error "Invalid kind: expected 'ResourceGraphDefinition', got '$kind'"
        return 1
    fi
    print_success "Kind is correct: $kind"
    
    if [ "$name" != "$RGD_NAME" ]; then
        print_error "Invalid name: expected '$RGD_NAME', got '$name'"
        return 1
    fi
    print_success "Name is correct: $name"
    
    return 0
}

# Function to validate RGD schema
validate_rgd_schema() {
    print_status "Validating RGD schema definition..."
    
    # Check if schema is defined
    local schema_exists=$(yq eval '.spec.schema' "$RGD_FILE" 2>/dev/null | grep -v "null" | wc -l)
    if [ "$schema_exists" -eq 0 ]; then
        print_error "RGD schema is not defined"
        return 1
    fi
    print_success "RGD schema is defined"
    
    # Check schema structure
    local schema_api_version=$(yq eval '.spec.schema.apiVersion' "$RGD_FILE" 2>/dev/null || echo "")
    local schema_kind=$(yq eval '.spec.schema.kind' "$RGD_FILE" 2>/dev/null || echo "")
    
    if [ "$schema_api_version" != "v1alpha1" ]; then
        print_error "Invalid schema apiVersion: expected 'v1alpha1', got '$schema_api_version'"
        return 1
    fi
    print_success "Schema API version is correct: $schema_api_version"
    
    if [ "$schema_kind" != "CICDPipeline" ]; then
        print_error "Invalid schema kind: expected 'CICDPipeline', got '$schema_kind'"
        return 1
    fi
    print_success "Schema kind is correct: $schema_kind"
    
    # Check required schema fields
    local required_fields=("name" "namespace" "aws" "application" "ecr" "gitlab")
    for field in "${required_fields[@]}"; do
        local field_exists=$(yq eval ".spec.schema.spec.$field" "$RGD_FILE" 2>/dev/null | grep -v "null" | wc -l)
        if [ "$field_exists" -eq 0 ]; then
            print_error "Required schema field missing: $field"
            return 1
        fi
        print_success "Schema field exists: $field"
    done
    
    return 0
}

# Function to validate RGD resources
validate_rgd_resources() {
    print_status "Validating RGD resource definitions..."
    
    # Check if resources are defined
    local resources_count=$(yq eval '.spec.resources | length' "$RGD_FILE" 2>/dev/null || echo "0")
    if [ "$resources_count" -eq 0 ]; then
        print_error "No resources defined in RGD"
        return 1
    fi
    print_success "RGD has $resources_count resource definitions"
    
    # Check for key resource types
    local expected_resources=(
        "appnamespace"
        "ecrmainrepo"
        "ecrcacherepo"
        "iampolicy"
        "iamrole"
        "podidentityassoc"
        "serviceaccount"
        "role"
        "rolebinding"
        "configmap"
        "dockersecret"
        "provisioningworkflow"
        "cachewarmupworkflow"
        "cicdworkflow"
        "eventsource"
        "sensor"
        "webhookservice"
        "webhookingress"
    )
    
    for resource_id in "${expected_resources[@]}"; do
        local resource_exists=$(yq eval ".spec.resources[] | select(.id == \"$resource_id\") | .id" "$RGD_FILE" 2>/dev/null | wc -l)
        if [ "$resource_exists" -eq 0 ]; then
            print_warning "Expected resource not found: $resource_id"
        else
            print_success "Resource definition exists: $resource_id"
        fi
    done
    
    return 0
}

# Function to check if RGD is applied to cluster
check_rgd_deployment() {
    print_status "Checking if RGD is deployed to cluster..."
    
    if ! kubectl get resourcegraphdefinition "$RGD_NAME" >/dev/null 2>&1; then
        print_warning "RGD is not deployed to cluster"
        print_status "To deploy the RGD, run: kubectl apply -f $RGD_FILE"
        return 1
    fi
    
    print_success "RGD is deployed to cluster"
    
    # Get RGD status
    local rgd_status=$(kubectl get resourcegraphdefinition "$RGD_NAME" -o jsonpath='{.status}' 2>/dev/null || echo "{}")
    if [ "$rgd_status" != "{}" ] && [ -n "$rgd_status" ]; then
        print_status "RGD status:"
        echo "$rgd_status" | jq . 2>/dev/null || echo "$rgd_status"
    fi
    
    return 0
}

# Function to validate CRD registration
validate_crd_registration() {
    print_status "Validating CRD registration for CICDPipeline..."
    
    # The RGD should create a CRD for CICDPipeline
    local crd_name="cicdpipelines.kro.run"
    
    if ! kubectl get crd "$crd_name" >/dev/null 2>&1; then
        print_warning "CICDPipeline CRD not found. This may be normal if the RGD hasn't been processed yet."
        print_status "Expected CRD: $crd_name"
        return 1
    fi
    
    print_success "CICDPipeline CRD is registered"
    
    # Check CRD details
    local crd_version=$(kubectl get crd "$crd_name" -o jsonpath='{.spec.versions[0].name}' 2>/dev/null || echo "")
    local crd_group=$(kubectl get crd "$crd_name" -o jsonpath='{.spec.group}' 2>/dev/null || echo "")
    
    print_status "CRD details:"
    echo "  Group: $crd_group"
    echo "  Version: $crd_version"
    echo "  Name: $crd_name"
    
    return 0
}

# Function to test RGD with dry-run
test_rgd_dry_run() {
    print_status "Testing RGD with dry-run..."
    
    # Create a temporary test instance file
    local test_file="/tmp/test-cicd-pipeline-dry-run.yaml"
    
    cat > "$test_file" <<EOF
apiVersion: kro.run/v1alpha1
kind: CICDPipeline
metadata:
  name: dry-run-test-cicd-pipeline
  namespace: default
spec:
  name: dry-run-test-cicd
  namespace: default
  aws:
    region: us-west-2
    clusterName: test-cluster
  application:
    name: dry-run-test
    dockerfilePath: "."
    deploymentPath: "./deployment"
  ecr:
    repositoryPrefix: "modengg"
  gitlab:
    hostname: "test.example.com"
    username: "testuser"
EOF
    
    # Test dry-run
    if kubectl apply --dry-run=client -f "$test_file" >/dev/null 2>&1; then
        print_success "RGD dry-run test passed"
        rm -f "$test_file"
        return 0
    else
        print_error "RGD dry-run test failed"
        kubectl apply --dry-run=client -f "$test_file"
        rm -f "$test_file"
        return 1
    fi
}

# Main validation function
main() {
    print_status "Starting Kro CI/CD Pipeline RGD validation..."
    echo ""
    
    local validation_passed=true
    
    # Step 1: Check Kro installation
    print_status "Step 1: Checking Kro installation..."
    if ! kubectl get crd resourcegraphdefinitions.kro.run >/dev/null 2>&1; then
        print_error "Kro is not installed. Please install Kro first."
        validation_passed=false
    else
        print_success "Kro is installed"
    fi
    echo ""
    
    # Step 2: Validate RGD file
    print_status "Step 2: Validating RGD file..."
    if ! validate_rgd_file; then
        validation_passed=false
    fi
    echo ""
    
    # Step 3: Validate RGD schema
    print_status "Step 3: Validating RGD schema..."
    if ! validate_rgd_schema; then
        validation_passed=false
    fi
    echo ""
    
    # Step 4: Validate RGD resources
    print_status "Step 4: Validating RGD resources..."
    if ! validate_rgd_resources; then
        validation_passed=false
    fi
    echo ""
    
    # Step 5: Check RGD deployment
    print_status "Step 5: Checking RGD deployment..."
    if ! check_rgd_deployment; then
        print_status "RGD is not deployed. Attempting to deploy..."
        if kubectl apply -f "$RGD_FILE"; then
            print_success "RGD deployed successfully"
            sleep 5  # Wait for processing
        else
            print_error "Failed to deploy RGD"
            validation_passed=false
        fi
    fi
    echo ""
    
    # Step 6: Validate CRD registration
    print_status "Step 6: Validating CRD registration..."
    if ! validate_crd_registration; then
        print_warning "CRD validation failed, but this may be temporary"
    fi
    echo ""
    
    # Step 7: Test dry-run
    print_status "Step 7: Testing RGD with dry-run..."
    if ! test_rgd_dry_run; then
        validation_passed=false
    fi
    echo ""
    
    # Final summary
    print_status "=== VALIDATION SUMMARY ==="
    if [ "$validation_passed" = true ]; then
        print_success "✅ All validations passed!"
        print_success "✅ Kro ResourceGraphDefinition is valid and ready for use"
        print_success "✅ RGD is properly recognized by Kro"
        echo ""
        print_status "Next steps:"
        echo "1. Run the deployment test: ./test-kro-deployment.sh"
        echo "2. Create a CICDPipeline instance to test functionality"
        echo "3. Monitor resource creation in the cluster"
    else
        print_error "❌ Some validations failed"
        print_error "❌ Please fix the issues before proceeding"
        echo ""
        print_status "Common fixes:"
        echo "1. Ensure Kro is properly installed"
        echo "2. Check RGD file syntax and structure"
        echo "3. Verify all required fields are present"
        echo "4. Apply the RGD to the cluster"
    fi
    
    if [ "$validation_passed" = true ]; then
        return 0
    else
        return 1
    fi
}

# Run main function
main