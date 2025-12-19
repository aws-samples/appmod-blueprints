#!/bin/bash

# Standalone Kro RGD validation script using Kro CLI
# This script validates the CI/CD Pipeline RGD using the Kro CLI tool

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
KRO_PATH="/Users/sallaman/Documents/2025/platform/kro"
RGD_PATH="/Users/sallaman/Documents/2025/platform/appmod-blueprints/gitops/addons/charts/kro/resource-groups/cicd-pipeline/cicd-pipeline.yaml"

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

# Main validation function
main() {
    print_status "Kro CI/CD Pipeline RGD CLI Validation"
    echo ""
    
    # Check if Kro source exists
    if [ ! -d "$KRO_PATH" ]; then
        print_error "Kro source code not found at $KRO_PATH"
        print_status "Please ensure Kro is cloned to the expected location"
        exit 1
    fi
    
    # Check if RGD file exists
    if [ ! -f "$RGD_PATH" ]; then
        print_error "RGD file not found at $RGD_PATH"
        exit 1
    fi
    
    print_status "Kro source path: $KRO_PATH"
    print_status "RGD file path: $RGD_PATH"
    echo ""
    
    print_status "Running Kro CLI validation..."
    echo ""
    
    # Set up Go environment and run validation
    cd "$KRO_PATH"
    export GOROOT=/opt/homebrew/Cellar/go/1.25.1/libexec
    export PATH="/opt/homebrew/bin:$PATH"
    
    # Run the validation command
    if go run ./cmd/kro/main.go validate rgd -f "$RGD_PATH"; then
        echo ""
        print_success "✅ Kro CLI validation passed!"
        print_success "✅ RGD is valid and ready for deployment"
        echo ""
        print_status "Next steps:"
        echo "1. Apply the RGD to your cluster: kubectl apply -f $RGD_PATH"
        echo "2. Create a CICDPipeline instance to test functionality"
        echo "3. Run the full deployment test: ./test-kro-deployment.sh"
        exit 0
    else
        echo ""
        print_error "❌ Kro CLI validation failed"
        print_error "❌ Please fix the RGD issues before proceeding"
        echo ""
        print_status "Common fixes:"
        echo "1. Check CEL expressions for syntax errors"
        echo "2. Verify resource dependencies and readyWhen conditions"
        echo "3. Ensure all referenced fields exist in the resource schemas"
        echo "4. Remove circular dependencies between resources"
        exit 1
    fi
}

# Handle script arguments
case "${1:-}" in
    "help"|"-h"|"--help")
        echo "Usage: $0"
        echo ""
        echo "This script validates the Kro CI/CD Pipeline RGD using the Kro CLI tool."
        echo ""
        echo "Requirements:"
        echo "- Kro source code at $KRO_PATH"
        echo "- Go installed and configured"
        echo "- RGD file at $RGD_PATH"
        exit 0
        ;;
    *)
        main
        ;;
esac