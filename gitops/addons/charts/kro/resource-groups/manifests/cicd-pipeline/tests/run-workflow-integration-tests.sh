#!/bin/bash

# Workflow Integration Test Runner for CI/CD Pipeline Kro RGD
# Tests Argo Workflows access, ECR authentication, and webhook triggering

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="${SCRIPT_DIR}/integration"
TEST_NAMESPACE="test-workflow-integration"
TIMEOUT=600 # 10 minutes

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

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check cluster connectivity
    if ! kubectl cluster-info &> /dev/null; then
        print_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    # Check if Kro is installed
    if ! kubectl get crd resourcegroupdefinitions.kro.run &> /dev/null; then
        print_error "Kro CRDs not found. Please install Kro first."
        exit 1
    fi
    
    # Check if Argo Workflows is installed
    if ! kubectl get crd workflows.argoproj.io &> /dev/null; then
        print_error "Argo Workflows CRDs not found. Please install Argo Workflows first."
        exit 1
    fi
    
    # Check if Argo Events is installed
    if ! kubectl get crd eventsources.argoproj.io &> /dev/null; then
        print_error "Argo Events CRDs not found. Please install Argo Events first."
        exit 1
    fi
    
    # Check if ACK controllers are available
    if ! kubectl get crd repositories.ecr.services.k8s.aws &> /dev/null; then
        print_warning "ACK ECR controller not found. Some tests may fail."
    fi
    
    print_success "Prerequisites check completed"
}

# Function to setup test environment
setup_test_environment() {
    print_status "Setting up test environment..."
    
    # Install test dependencies
    cd "${TEST_DIR}"
    if [ -f package.json ]; then
        print_status "Installing test dependencies..."
        npm install
    fi
    
    print_success "Test environment setup completed"
}

# Function to run workflow integration tests
run_workflow_tests() {
    print_status "Running workflow integration tests..."
    
    cd "${TEST_DIR}"
    
    # Run the workflow integration tests
    if npm test -- workflow-integration.test.js --run; then
        print_success "Workflow integration tests passed"
        return 0
    else
        print_error "Workflow integration tests failed"
        return 1
    fi
}

# Function to cleanup test resources
cleanup_test_resources() {
    print_status "Cleaning up test resources..."
    
    # Delete test namespace if it exists
    if kubectl get namespace "${TEST_NAMESPACE}" &> /dev/null; then
        print_status "Deleting test namespace: ${TEST_NAMESPACE}"
        kubectl delete namespace "${TEST_NAMESPACE}" --timeout=300s || true
    fi
    
    # Wait for namespace deletion
    local count=0
    while kubectl get namespace "${TEST_NAMESPACE}" &> /dev/null && [ $count -lt 60 ]; do
        print_status "Waiting for namespace deletion..."
        sleep 5
        ((count++))
    done
    
    print_success "Cleanup completed"
}

# Function to display test results
display_results() {
    local exit_code=$1
    
    echo
    echo "=================================="
    echo "  Workflow Integration Test Results"
    echo "=================================="
    
    if [ $exit_code -eq 0 ]; then
        print_success "All workflow integration tests passed!"
        echo
        echo "✅ Argo Workflows access to provisioned resources"
        echo "✅ ECR authentication and image operations"
        echo "✅ Webhook triggering and build processes"
        echo "✅ End-to-end workflow integration"
    else
        print_error "Some workflow integration tests failed!"
        echo
        echo "❌ Check the test output above for details"
        echo "❌ Ensure all prerequisites are installed"
        echo "❌ Verify cluster has necessary permissions"
    fi
    
    echo "=================================="
}

# Main execution
main() {
    echo "========================================"
    echo "  CI/CD Pipeline Workflow Integration Tests"
    echo "========================================"
    echo
    
    # Parse command line arguments
    CLEANUP_ONLY=false
    SKIP_CLEANUP=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --cleanup-only)
                CLEANUP_ONLY=true
                shift
                ;;
            --skip-cleanup)
                SKIP_CLEANUP=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo
                echo "Options:"
                echo "  --cleanup-only    Only run cleanup, skip tests"
                echo "  --skip-cleanup    Skip cleanup after tests"
                echo "  --help, -h        Show this help message"
                echo
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # If cleanup only, just run cleanup and exit
    if [ "$CLEANUP_ONLY" = true ]; then
        cleanup_test_resources
        exit 0
    fi
    
    local exit_code=0
    
    # Run the test workflow
    check_prerequisites || exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        setup_test_environment || exit_code=$?
    fi
    
    if [ $exit_code -eq 0 ]; then
        run_workflow_tests || exit_code=$?
    fi
    
    # Cleanup unless skipped
    if [ "$SKIP_CLEANUP" != true ]; then
        cleanup_test_resources
    fi
    
    # Display results
    display_results $exit_code
    
    exit $exit_code
}

# Handle script interruption
trap 'print_warning "Script interrupted. Running cleanup..."; cleanup_test_resources; exit 130' INT TERM

# Run main function
main "$@"