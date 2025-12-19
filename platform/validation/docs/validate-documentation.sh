#!/bin/bash

# Documentation Validation Script
# This script validates the Platform Engineering on EKS documentation
# for completeness, consistency, and user journey effectiveness

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Test result tracking
declare -a FAILED_TEST_NAMES=()

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED_TESTS++))
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED_TESTS++))
    FAILED_TEST_NAMES+=("$1")
}

run_test() {
    local test_name="$1"
    local test_command="$2"
    
    ((TOTAL_TESTS++))
    log_info "Running test: $test_name"
    
    if eval "$test_command"; then
        log_success "$test_name"
        return 0
    else
        log_error "$test_name"
        return 1
    fi
}

# Test functions
test_file_exists() {
    local file="$1"
    local description="$2"
    
    if [[ -f "$file" ]]; then
        log_success "File exists: $description ($file)"
        ((PASSED_TESTS++))
        return 0
    else
        log_error "File missing: $description ($file)"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("File missing: $description")
        return 1
    fi
    ((TOTAL_TESTS++))
}

test_metadata_present() {
    local file="$1"
    local description="$2"
    
    ((TOTAL_TESTS++))
    
    if [[ ! -f "$file" ]]; then
        log_error "Cannot test metadata - file missing: $file"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("Metadata test failed - file missing: $description")
        return 1
    fi
    
    # Check for YAML frontmatter
    if head -n 20 "$file" | grep -q "^---$"; then
        log_success "Metadata present: $description"
        ((PASSED_TESTS++))
        return 0
    else
        log_error "Metadata missing: $description ($file)"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("Metadata missing: $description")
        return 1
    fi
}

test_cross_references() {
    local file="$1"
    local description="$2"
    
    ((TOTAL_TESTS++))
    
    if [[ ! -f "$file" ]]; then
        log_error "Cannot test cross-references - file missing: $file"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("Cross-reference test failed - file missing: $description")
        return 1
    fi
    
    # Check for cross-repository references
    local cross_refs=0
    if grep -q "platform-engineering-on-eks" "$file" || grep -q "appmod-blueprints" "$file"; then
        ((cross_refs++))
    fi
    
    # Check for internal references
    if grep -q "\[.*\](.*\.md)" "$file"; then
        ((cross_refs++))
    fi
    
    if [[ $cross_refs -gt 0 ]]; then
        log_success "Cross-references present: $description"
        ((PASSED_TESTS++))
        return 0
    else
        log_warning "Limited cross-references: $description ($file)"
        ((PASSED_TESTS++))  # Not a failure, just a warning
        return 0
    fi
}

test_persona_content() {
    local file="$1"
    local description="$2"
    
    ((TOTAL_TESTS++))
    
    if [[ ! -f "$file" ]]; then
        log_error "Cannot test persona content - file missing: $file"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("Persona content test failed - file missing: $description")
        return 1
    fi
    
    # Check for persona-specific content markers
    local persona_markers=0
    if grep -q "workshop.*participant\|Workshop.*Participant" "$file"; then
        ((persona_markers++))
    fi
    if grep -q "platform.*adopter\|Platform.*Adopter" "$file"; then
        ((persona_markers++))
    fi
    if grep -q "infrastructure.*engineer\|Infrastructure.*Engineer" "$file"; then
        ((persona_markers++))
    fi
    if grep -q "developer\|Developer" "$file"; then
        ((persona_markers++))
    fi
    
    if [[ $persona_markers -gt 0 ]]; then
        log_success "Persona content present: $description ($persona_markers personas referenced)"
        ((PASSED_TESTS++))
        return 0
    else
        log_error "No persona content found: $description ($file)"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("No persona content: $description")
        return 1
    fi
}

test_deployment_scenarios() {
    local file="$1"
    local description="$2"
    
    ((TOTAL_TESTS++))
    
    if [[ ! -f "$file" ]]; then
        log_error "Cannot test deployment scenarios - file missing: $file"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("Deployment scenarios test failed - file missing: $description")
        return 1
    fi
    
    # Check for deployment scenario content
    local scenarios=0
    if grep -qi "full.*workshop\|workshop.*stack" "$file"; then
        ((scenarios++))
    fi
    if grep -qi "platform.*only\|platform.*deployment" "$file"; then
        ((scenarios++))
    fi
    if grep -qi "ide.*only\|development.*environment" "$file"; then
        ((scenarios++))
    fi
    if grep -qi "manual.*setup\|custom.*implementation" "$file"; then
        ((scenarios++))
    fi
    
    if [[ $scenarios -ge 2 ]]; then
        log_success "Deployment scenarios present: $description ($scenarios scenarios found)"
        ((PASSED_TESTS++))
        return 0
    else
        log_warning "Limited deployment scenarios: $description ($scenarios scenarios found)"
        ((PASSED_TESTS++))  # Not a failure for all files
        return 0
    fi
}

test_troubleshooting_content() {
    local file="$1"
    local description="$2"
    
    ((TOTAL_TESTS++))
    
    if [[ ! -f "$file" ]]; then
        log_error "Cannot test troubleshooting content - file missing: $file"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("Troubleshooting test failed - file missing: $description")
        return 1
    fi
    
    # Check for troubleshooting indicators
    local troubleshooting_content=0
    if grep -qi "troubleshoot\|common.*issue\|error\|problem\|solution\|fix" "$file"; then
        ((troubleshooting_content++))
    fi
    if grep -q "kubectl\|aws.*cli\|diagnostic" "$file"; then
        ((troubleshooting_content++))
    fi
    
    if [[ $troubleshooting_content -gt 0 ]]; then
        log_success "Troubleshooting content present: $description"
        ((PASSED_TESTS++))
        return 0
    else
        log_warning "Limited troubleshooting content: $description"
        ((PASSED_TESTS++))  # Not all files need troubleshooting content
        return 0
    fi
}

test_ai_context_completeness() {
    local file="$1"
    local description="$2"
    
    ((TOTAL_TESTS++))
    
    if [[ ! -f "$file" ]]; then
        log_error "Cannot test AI context - file missing: $file"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("AI context test failed - file missing: $description")
        return 1
    fi
    
    # Check for AI context indicators
    local ai_content=0
    if grep -qi "project.*overview\|architecture.*overview" "$file"; then
        ((ai_content++))
    fi
    if grep -qi "key.*concept\|terminology" "$file"; then
        ((ai_content++))
    fi
    if grep -qi "interaction.*pattern\|workflow" "$file"; then
        ((ai_content++))
    fi
    if grep -qi "troubleshooting.*pattern\|diagnostic" "$file"; then
        ((ai_content++))
    fi
    
    if [[ $ai_content -ge 3 ]]; then
        log_success "AI context comprehensive: $description ($ai_content content areas found)"
        ((PASSED_TESTS++))
        return 0
    else
        log_error "AI context incomplete: $description ($ai_content content areas found, need 3+)"
        ((FAILED_TESTS++))
        FAILED_TEST_NAMES+=("AI context incomplete: $description")
        return 1
    fi
}

# Main validation function
main() {
    log_info "Starting Platform Engineering on EKS Documentation Validation"
    log_info "================================================================"
    
    # Test repository structure
    log_info "\n1. Testing Repository Structure"
    log_info "--------------------------------"
    
    # Platform Engineering on EKS repository
    test_file_exists "platform-engineering-on-eks/README.md" "Platform Engineering README"
    test_file_exists "platform-engineering-on-eks/GETTING-STARTED.md" "Platform Engineering Getting Started"
    test_file_exists "platform-engineering-on-eks/ARCHITECTURE.md" "Platform Engineering Architecture"
    test_file_exists "platform-engineering-on-eks/DEPLOYMENT-GUIDE.md" "Platform Engineering Deployment Guide"
    test_file_exists "platform-engineering-on-eks/TROUBLESHOOTING.md" "Platform Engineering Troubleshooting"
    test_file_exists "platform-engineering-on-eks/AI-CONTEXT.md" "Platform Engineering AI Context"
    
    # Application Modernization Blueprints repository
    test_file_exists "appmod-blueprints/README.md" "App Mod Blueprints README"
    test_file_exists "appmod-blueprints/GETTING-STARTED.md" "App Mod Blueprints Getting Started"
    test_file_exists "appmod-blueprints/ARCHITECTURE.md" "App Mod Blueprints Architecture"
    test_file_exists "appmod-blueprints/DEPLOYMENT-GUIDE.md" "App Mod Blueprints Deployment Guide"
    test_file_exists "appmod-blueprints/TROUBLESHOOTING.md" "App Mod Blueprints Troubleshooting"
    test_file_exists "appmod-blueprints/AI-CONTEXT.md" "App Mod Blueprints AI Context"
    
    # Test metadata presence
    log_info "\n2. Testing Document Metadata"
    log_info "-----------------------------"
    
    test_metadata_present "platform-engineering-on-eks/README.md" "Platform Engineering README metadata"
    test_metadata_present "platform-engineering-on-eks/GETTING-STARTED.md" "Platform Engineering Getting Started metadata"
    test_metadata_present "appmod-blueprints/README.md" "App Mod Blueprints README metadata"
    test_metadata_present "appmod-blueprints/GETTING-STARTED.md" "App Mod Blueprints Getting Started metadata"
    
    # Test cross-repository references
    log_info "\n3. Testing Cross-Repository References"
    log_info "--------------------------------------"
    
    test_cross_references "platform-engineering-on-eks/README.md" "Platform Engineering README cross-refs"
    test_cross_references "appmod-blueprints/README.md" "App Mod Blueprints README cross-refs"
    test_cross_references "platform-engineering-on-eks/GETTING-STARTED.md" "Platform Engineering Getting Started cross-refs"
    test_cross_references "appmod-blueprints/GETTING-STARTED.md" "App Mod Blueprints Getting Started cross-refs"
    
    # Test persona-specific content
    log_info "\n4. Testing Persona-Specific Content"
    log_info "-----------------------------------"
    
    test_persona_content "platform-engineering-on-eks/README.md" "Platform Engineering README personas"
    test_persona_content "platform-engineering-on-eks/GETTING-STARTED.md" "Platform Engineering Getting Started personas"
    test_persona_content "appmod-blueprints/README.md" "App Mod Blueprints README personas"
    test_persona_content "appmod-blueprints/GETTING-STARTED.md" "App Mod Blueprints Getting Started personas"
    
    # Test deployment scenarios
    log_info "\n5. Testing Deployment Scenarios"
    log_info "-------------------------------"
    
    test_deployment_scenarios "platform-engineering-on-eks/GETTING-STARTED.md" "Platform Engineering deployment scenarios"
    test_deployment_scenarios "platform-engineering-on-eks/DEPLOYMENT-GUIDE.md" "Platform Engineering deployment guide scenarios"
    test_deployment_scenarios "appmod-blueprints/GETTING-STARTED.md" "App Mod Blueprints deployment scenarios"
    test_deployment_scenarios "appmod-blueprints/DEPLOYMENT-GUIDE.md" "App Mod Blueprints deployment guide scenarios"
    
    # Test troubleshooting content
    log_info "\n6. Testing Troubleshooting Content"
    log_info "----------------------------------"
    
    if [[ -f "platform-engineering-on-eks/TROUBLESHOOTING.md" ]]; then
        test_troubleshooting_content "platform-engineering-on-eks/TROUBLESHOOTING.md" "Platform Engineering troubleshooting"
    fi
    if [[ -f "appmod-blueprints/TROUBLESHOOTING.md" ]]; then
        test_troubleshooting_content "appmod-blueprints/TROUBLESHOOTING.md" "App Mod Blueprints troubleshooting"
    fi
    test_troubleshooting_content "platform-engineering-on-eks/GETTING-STARTED.md" "Platform Engineering getting started troubleshooting"
    test_troubleshooting_content "appmod-blueprints/GETTING-STARTED.md" "App Mod Blueprints getting started troubleshooting"
    
    # Test AI context completeness
    log_info "\n7. Testing AI Context Documents"
    log_info "-------------------------------"
    
    test_ai_context_completeness "platform-engineering-on-eks/AI-CONTEXT.md" "Platform Engineering AI context"
    test_ai_context_completeness "appmod-blueprints/AI-CONTEXT.md" "App Mod Blueprints AI context"
    
    # Summary
    log_info "\n8. Validation Summary"
    log_info "====================\n"
    
    log_info "Total tests run: $TOTAL_TESTS"
    log_success "Tests passed: $PASSED_TESTS"
    
    if [[ $FAILED_TESTS -gt 0 ]]; then
        log_error "Tests failed: $FAILED_TESTS"
        log_info "\nFailed tests:"
        for test_name in "${FAILED_TEST_NAMES[@]}"; do
            echo -e "  ${RED}✗${NC} $test_name"
        done
    else
        log_success "All tests passed!"
    fi
    
    # Calculate success rate
    local success_rate=$((PASSED_TESTS * 100 / TOTAL_TESTS))
    log_info "\nSuccess rate: ${success_rate}%"
    
    if [[ $success_rate -ge 90 ]]; then
        log_success "Documentation validation: EXCELLENT (≥90%)"
        exit 0
    elif [[ $success_rate -ge 80 ]]; then
        log_success "Documentation validation: GOOD (≥80%)"
        exit 0
    elif [[ $success_rate -ge 70 ]]; then
        log_warning "Documentation validation: ACCEPTABLE (≥70%)"
        exit 1
    else
        log_error "Documentation validation: NEEDS IMPROVEMENT (<70%)"
        exit 1
    fi
}

# Check if we're in the right directory
if [[ ! -d "platform-engineering-on-eks" && ! -d "appmod-blueprints" ]]; then
    log_error "This script should be run from a directory containing both platform-engineering-on-eks and appmod-blueprints directories"
    log_info "Current directory: $(pwd)"
    log_info "Available directories: $(ls -d */ 2>/dev/null || echo 'none')"
    exit 1
fi

# Run main validation
main "$@"