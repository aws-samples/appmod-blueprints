#!/bin/bash

# Script to fix all Backstage templates for GitLab and ArgoCD compatibility
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
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

print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

print_header "Fixing All Backstage Templates for GitLab and ArgoCD"

# Find all template files
TEMPLATE_FILES=$(find platform/backstage/templates -name "*.yaml" -type f)

if [ -z "$TEMPLATE_FILES" ]; then
    print_warning "No template files found"
    exit 0
fi

print_info "Found template files to process:"
echo "$TEMPLATE_FILES" | while read -r file; do
    echo "  - $file"
done

# Process each template file
echo "$TEMPLATE_FILES" | while read -r template_file; do
    print_info "Processing $template_file"
    
    # Create backup
    cp "$template_file" "$template_file.backup"
    
    CHANGES_MADE=false
    
    # Fix publish:gitlab action - remove description parameter
    if grep -q "publish:gitlab" "$template_file" && grep -q "description:" "$template_file"; then
        print_info "  Fixing GitLab publish action in $template_file"
        
        # Remove the description line from publish:gitlab input sections
        sed -i '/action: publish:gitlab/,/^    - id:/{
            /description:/d
        }' "$template_file"
        
        CHANGES_MADE=true
    fi
    
    # Update cnoe:create-argocd-app to argocd:create-app
    if grep -q "cnoe:create-argocd-app" "$template_file"; then
        print_info "  Updating ArgoCD action in $template_file"
        sed -i 's/action: cnoe:create-argocd-app/action: argocd:create-app/g' "$template_file"
        CHANGES_MADE=true
    fi
    
    # Fix repoUrl format for GitLab (remove gitea references and fix URL structure)
    if grep -q "repoUrl.*gitea" "$template_file"; then
        print_info "  Fixing GitLab repoUrl format in $template_file"
        
        # Fix the repoUrl format to be compatible with GitLab
        sed -i 's|repoUrl: \${{ steps\['\''fetchSystem'\''\]\.output\.entity\.spec\.hostname }}/d31l55m8hkb7r3\.cloudfront\.net/user1?repo=\${{parameters\.[^}]*}}|repoUrl: \${{ steps['\''fetchSystem'\''].output.entity.spec.hostname }}/user1?repo=\${{parameters.bucket_name}}\&owner=user1|g' "$template_file"
        
        # More generic gitea URL fixes
        sed -i 's|/gitea|/user1|g' "$template_file"
        sed -i 's|giteaAdmin|user1|g' "$template_file"
        
        CHANGES_MADE=true
    fi
    
    # Update ArgoCD repoUrl to use the published repository
    if grep -q "argocd:create-app" "$template_file" && grep -q "repoUrl: http://my-gitea" "$template_file"; then
        print_info "  Updating ArgoCD repoUrl to use published repository"
        sed -i 's|repoUrl: http://my-gitea-http\.gitea\.svc\.cluster\.local:3000/giteaAdmin/\${{parameters\.[^}]*}}|repoUrl: \${{ steps['\''publish'\''].output.remoteUrl }}|g' "$template_file"
        CHANGES_MADE=true
    fi
    
    if [ "$CHANGES_MADE" = true ]; then
        print_success "  Updated $template_file"
    else
        print_info "  No changes needed for $template_file"
        # Remove backup if no changes were made
        rm "$template_file.backup"
    fi
done

print_header "Update Summary"

# Count updated files
GITLAB_COUNT=$(find appmod-blueprints/platform/backstage/templates -name "*.yaml" -exec grep -l "publish:gitlab" {} \; | wc -l)
ARGOCD_COUNT=$(find appmod-blueprints/platform/backstage/templates -name "*.yaml" -exec grep -l "argocd:create-app" {} \; | wc -l)

print_success "Templates using publish:gitlab: $GITLAB_COUNT"
print_success "Templates using argocd:create-app: $ARGOCD_COUNT"

print_info "Changes made:"
echo "  ✓ Removed 'description' parameter from publish:gitlab actions"
echo "  ✓ Updated 'cnoe:create-argocd-app' to 'argocd:create-app'"
echo "  ✓ Fixed GitLab repoUrl formats"
echo "  ✓ Updated ArgoCD repoUrl to use published repository URLs"

print_info "Backup files created for modified templates with .backup extension"
print_info "You can remove backups with: find appmod-blueprints/platform/backstage/templates -name '*.backup' -delete"

print_success "All templates processed successfully!"