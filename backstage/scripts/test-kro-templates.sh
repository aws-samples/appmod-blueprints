#!/bin/bash

# Test script for Kro ResourceGroup templates
# This script validates the template structure and YAML syntax

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="$SCRIPT_DIR/../examples/templates"
TEMP_DIR="/tmp/kro-template-test"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if required tools are available
check_dependencies() {
    log_info "Checking dependencies..."
    
    if ! command -v yq &> /dev/null; then
        log_error "yq is required but not installed. Please install yq."
        exit 1
    fi
    
    if ! command -v kubectl &> /dev/null; then
        log_warn "kubectl is not installed. Kubernetes validation will be skipped."
    fi
    
    log_info "Dependencies check completed."
}

# Validate YAML syntax (skip template files with Nunjucks)
validate_yaml() {
    local file="$1"
    log_info "Validating YAML syntax: $file"
    
    # Skip YAML validation for files containing Nunjucks templates
    if grep -q '{%\|{{' "$file"; then
        log_info "✓ Skipping YAML validation (contains templates): $file"
        return 0
    fi
    
    if yq eval '.' "$file" > /dev/null 2>&1; then
        log_info "✓ YAML syntax is valid: $file"
        return 0
    else
        log_error "✗ YAML syntax error in: $file"
        return 1
    fi
}

# Validate template structure
validate_template_structure() {
    local template_file="$1"
    local template_name="$2"
    
    log_info "Validating template structure: $template_name"
    
    # Check required fields
    local required_fields=(
        ".apiVersion"
        ".kind"
        ".metadata.name"
        ".metadata.title"
        ".metadata.description"
        ".spec.owner"
        ".spec.type"
        ".spec.parameters"
        ".spec.steps"
        ".spec.output"
    )
    
    for field in "${required_fields[@]}"; do
        if ! yq eval "$field" "$template_file" > /dev/null 2>&1; then
            log_error "✗ Missing required field: $field in $template_name"
            return 1
        fi
    done
    
    # Check if it's a scaffolder template
    local api_version=$(yq eval '.apiVersion' "$template_file")
    local kind=$(yq eval '.kind' "$template_file")
    
    if [[ "$api_version" != "scaffolder.backstage.io/v1beta3" ]]; then
        log_error "✗ Invalid apiVersion: $api_version (expected: scaffolder.backstage.io/v1beta3)"
        return 1
    fi
    
    if [[ "$kind" != "Template" ]]; then
        log_error "✗ Invalid kind: $kind (expected: Template)"
        return 1
    fi
    
    # Check if spec.type is kro-resource-group
    local spec_type=$(yq eval '.spec.type' "$template_file")
    if [[ "$spec_type" != "kro-resource-group" ]]; then
        log_error "✗ Invalid spec.type: $spec_type (expected: kro-resource-group)"
        return 1
    fi
    
    log_info "✓ Template structure is valid: $template_name"
    return 0
}

# Validate content files
validate_content_files() {
    local template_dir="$1"
    local template_name="$2"
    
    log_info "Validating content files: $template_name"
    
    local content_dir="$template_dir/content"
    if [[ ! -d "$content_dir" ]]; then
        log_error "✗ Content directory not found: $content_dir"
        return 1
    fi
    
    # Check required content files
    local required_files=(
        "catalog-info.yaml"
        "resourcegroup.yaml"
        "instance.yaml"
        "README.md"
    )
    
    for file in "${required_files[@]}"; do
        local file_path="$content_dir/$file"
        if [[ ! -f "$file_path" ]]; then
            log_error "✗ Required content file not found: $file"
            return 1
        fi
        
        # Validate YAML files
        if [[ "$file" == *.yaml ]]; then
            if ! validate_yaml "$file_path"; then
                return 1
            fi
        fi
    done
    
    log_info "✓ Content files are valid: $template_name"
    return 0
}



# Test template rendering (basic check)
test_template_rendering() {
    local template_dir="$1"
    local template_name="$2"
    
    log_info "Testing template rendering: $template_name"
    
    # Create a temporary directory for testing
    local test_dir="$TEMP_DIR/$template_name"
    mkdir -p "$test_dir"
    
    # Copy content files to test directory
    cp -r "$template_dir/content/"* "$test_dir/"
    
    # Check for template variables (basic check)
    local template_files=("$test_dir"/*.yaml "$test_dir"/*.md)
    for file in "${template_files[@]}"; do
        if [[ -f "$file" ]]; then
            # Check for unresolved template variables (this is a basic check)
            if grep -q '\${{.*}}' "$file"; then
                log_info "Template variables found in: $(basename "$file")"
            fi
        fi
    done
    
    log_info "✓ Template rendering test completed: $template_name"
    return 0
}

# Main validation function
validate_template() {
    local template_dir="$1"
    local template_name=$(basename "$template_dir")
    
    log_info "Starting validation for template: $template_name"
    
    local template_file="$template_dir/template.yaml"
    if [[ ! -f "$template_file" ]]; then
        log_error "✗ Template file not found: $template_file"
        return 1
    fi
    
    # Validate template file
    if ! validate_yaml "$template_file"; then
        return 1
    fi
    
    if ! validate_template_structure "$template_file" "$template_name"; then
        return 1
    fi
    
    # Validate content files
    if ! validate_content_files "$template_dir" "$template_name"; then
        return 1
    fi
    
    # Validate specific files (skip for template files)
    local content_dir="$template_dir/content"
    
    # Basic structure validation for ResourceGroup template
    log_info "Validating ResourceGroup template structure: $template_name"
    local resourcegroup_file="$content_dir/resourcegroup.yaml"
    
    if ! grep -q "apiVersion.*kro.run" "$resourcegroup_file"; then
        log_error "✗ ResourceGroup file should contain kro.run apiVersion"
        return 1
    fi
    
    if ! grep -q "kind.*ResourceGraphDefinition" "$resourcegroup_file"; then
        log_error "✗ ResourceGroup file should contain ResourceGraphDefinition kind"
        return 1
    fi
    
    log_info "✓ ResourceGroup template structure is valid: $template_name"
    
    # Basic structure validation for catalog-info
    log_info "Validating catalog-info template structure: $template_name"
    local catalog_file="$content_dir/catalog-info.yaml"
    
    if ! grep -q "apiVersion.*backstage.io" "$catalog_file"; then
        log_error "✗ Catalog-info file should contain backstage.io apiVersion"
        return 1
    fi
    
    if ! grep -q "kind.*Component" "$catalog_file"; then
        log_error "✗ Catalog-info file should contain Component kind"
        return 1
    fi
    
    log_info "✓ Catalog-info template structure is valid: $template_name"
    
    # Test template rendering
    if ! test_template_rendering "$template_dir" "$template_name"; then
        return 1
    fi
    
    log_info "✓ All validations passed for template: $template_name"
    return 0
}

# Main function
main() {
    log_info "Starting Kro ResourceGroup template validation..."
    
    # Check dependencies
    check_dependencies
    
    # Create temporary directory
    mkdir -p "$TEMP_DIR"
    
    # Find all template directories
    local template_dirs=()
    if [[ -d "$TEMPLATES_DIR" ]]; then
        for template_dir in "$TEMPLATES_DIR"/*/; do
            if [[ -f "$template_dir/template.yaml" ]]; then
                template_dirs+=("$template_dir")
            fi
        done
    else
        log_error "Templates directory not found: $TEMPLATES_DIR"
        exit 1
    fi
    
    if [[ ${#template_dirs[@]} -eq 0 ]]; then
        log_error "No templates found in: $TEMPLATES_DIR"
        exit 1
    fi
    
    log_info "Found ${#template_dirs[@]} template(s) to validate"
    
    # Validate each template
    local failed_templates=()
    for template_dir in "${template_dirs[@]}"; do
        if ! validate_template "$template_dir"; then
            failed_templates+=("$(basename "$template_dir")")
        fi
        echo # Add blank line between templates
    done
    
    # Cleanup
    rm -rf "$TEMP_DIR"
    
    # Summary
    log_info "Validation Summary:"
    log_info "Total templates: ${#template_dirs[@]}"
    log_info "Passed: $((${#template_dirs[@]} - ${#failed_templates[@]}))"
    log_info "Failed: ${#failed_templates[@]}"
    
    if [[ ${#failed_templates[@]} -gt 0 ]]; then
        log_error "Failed templates: ${failed_templates[*]}"
        exit 1
    else
        log_info "All templates passed validation! ✓"
        exit 0
    fi
}

# Run main function
main "$@"