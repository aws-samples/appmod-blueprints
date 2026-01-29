#!/bin/bash
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/colors.sh"

print_header "Workshop Setup Validation"

# Track overall status
OVERALL_STATUS=0

# Check 1: ArgoCD Applications
print_step "Checking ArgoCD applications..."
if "$SCRIPT_DIR/recover-argocd-apps.sh"; then
    print_success "ArgoCD check completed"
else
    print_error "ArgoCD check failed"
    OVERALL_STATUS=1
fi

echo ""

# Check 2: Ray+vLLM CodeBuild
print_step "Checking Ray+vLLM image build..."
if "$SCRIPT_DIR/check-ray-build.sh"; then
    print_success "Ray build check completed"
else
    print_error "Ray build check failed"
    OVERALL_STATUS=1
fi

echo ""

# Final summary
print_header "Validation Summary"
if [ $OVERALL_STATUS -eq 0 ]; then
    print_success "All workshop components are healthy!"
else
    print_warning "Some components need attention. Review the output above."
fi

exit $OVERALL_STATUS
