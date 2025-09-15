#!/bin/bash

# Script to remove description parameter from publish:gitlab actions
set -e

print_info() {
    echo "[INFO] $1"
}

print_success() {
    echo "[SUCCESS] $1"
}

print_info "Removing description parameter from publish:gitlab actions..."

# Find all template files with publish:gitlab
TEMPLATE_FILES=$(find platform/backstage/templates -name "*.yaml" -exec grep -l "publish:gitlab" {} \;)

for template_file in $TEMPLATE_FILES; do
    print_info "Processing $template_file"
    
    # Check if this file has description in a publish:gitlab section
    if grep -A 10 "action: publish:gitlab" "$template_file" | grep -q "description:"; then
        print_info "  Removing description parameter from $template_file"
        
        # Create backup
        cp "$template_file" "$template_file.backup"
        
        # Use awk to remove description lines that appear after publish:gitlab
        awk '
        /action: publish:gitlab/ { in_gitlab = 1 }
        /^    - id:/ && in_gitlab { in_gitlab = 0 }
        !(in_gitlab && /description:/) { print }
        ' "$template_file" > "$template_file.tmp" && mv "$template_file.tmp" "$template_file"
        
        print_success "  Updated $template_file"
    else
        print_info "  No description parameter found in $template_file"
    fi
done

print_success "All templates processed!"