#!/bin/bash

# Simple validation script for Kro ResourceGroup templates
# This script validates the template structure without processing Nunjucks templates

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="$SCRIPT_DIR/../examples/templates"

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

# Validate template.yaml files
validate_template() {
    local template_file="$1"
    local template_name="$2"
    
    log_info "Validating template: $template_name"
    
    # Check if file exists
    if [[ ! -f "$template_file" ]]; then
        log_error "Template file not found: $template_file"
        return 1
    fi
    
    # Validate YAML syntax
    if ! yq eval '.' "$template_file" > /dev/null 2>&1; then
        log_error "Invalid YAML syntax in: $template_file"
        return 1
    fi
    
    # Check required fields
    local api_version=$(yq eval '.apiVersion' "$template_file" 2>/dev/null)
    local kind=$(yq eval '.kind' "$template_file" 2>/dev/null)
    local spec_type=$(yq eval '.spec.type' "$template_file" 2>/dev/null)
    
    if [[ "$api_version" != "scaffolder.backstage.io/v1beta3" ]]; then
        log_error "Invalid apiVersion: $api_version (expected: scaffolder.backstage.io/v1beta3)"
        return 1
    fi
    
    if [[ "$kind" != "Template" ]]; then
        log_error "Invalid kind: $kind (expected: Template)"
        return 1
    fi
    
    if [[ "$spec_type" != "kro-resource-group" ]]; then
        log_error "Invalid spec.type: $spec_type (expected: kro-resource-group)"
        return 1
    fi
    
    log_info "✓ Template is valid: $template_name"
    return 0
}

# Check content directory structure
validate_content_structure() {
    local template_dir="$1"
    local template_name="$2"
    
    log_info "Validating content structure: $template_name"
    
    local content_dir="$template_dir/content"
    if [[ ! -d "$content_dir" ]]; then
        log_error "Content directory not found: $content_dir"
        return 1
    fi
    
    # Check required files
    local required_files=(
        "catalog-info.yaml"
        "resourcegroup.yaml"
        "instance.yaml"
        "README.md"
    )
    
    for file in "${required_files[@]}"; do
        local file_path="$content_dir/$file"
        if [[ ! -f "$file_path" ]]; then
            log_error "Required file not found: $file"
            return 1
        fi
    done
    
    # Validate catalog-info.yaml (should be valid YAML without templates)
    if ! yq eval '.' "$content_dir/catalog-info.yaml" > /dev/null 2>&1; then
        log_error "Invalid YAML syntax in catalog-info.yaml"
        return 1
    fi
    
    # Check catalog-info structure
    local catalog_api_version=$(yq eval '.apiVersion' "$content_dir/catalog-info.yaml" 2>/dev/null)
    local catalog_kind=$(yq eval '.kind' "$content_dir/catalog-info.yaml" 2>/dev/null)
    
    if [[ "$catalog_api_version" != "backstage.io/v1alpha1" ]]; then
        log_error "Invalid catalog-info apiVersion: $catalog_api_version"
        return 1
    fi
    
    if [[ "$catalog_kind" != "Component" ]]; then
        log_error "Invalid catalog-info kind: $catalog_kind"
        return 1
    fi
    
    log_info "✓ Content structure is valid: $template_name"
    return 0
}

# Main function
main() {
    log_info "Starting Kro ResourceGroup template validation..."
    
    # Check if yq is available
    if ! command -v yq &> /dev/null; then
        log_error "yq is required but not installed. Please install yq."
        exit 1
    fi
    
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
        local template_name=$(basename "$template_dir")
        local template_file="$template_dir/template.yaml"
        
        if ! validate_template "$template_file" "$template_name"; then
            failed_templates+=("$template_name")
        elif ! validate_content_structure "$template_dir" "$template_name"; then
            failed_templates+=("$template_name")
        fi
        echo # Add blank line between templates
    done
    
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