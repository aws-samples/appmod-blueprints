#!/bin/bash

#############################################################################
# GitLab Repository Creation Script
# Creates repositories if they don't exist and populates them with content
# Replaces the original hanging script with a working version
#############################################################################

# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

# Remove set -e to prevent script from exiting on errors
# set -e

# Configuration
export GITLAB_URL="https://d31l55m8hkb7r3.cloudfront.net"
export GITLAB_PASSWORD="M0DZcEkDbyJiRLdJ9OW7kxj7eYeSbmb8"
export REPO_ROOT=$(git rev-parse --show-toplevel)
# Get environment variables
export GITLAB_URL=${GITLAB_URL:-$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'gitlab')].DomainName | [0]" --output text | sed 's/^/https:\/\//')}
export GITLAB_PASSWORD=${GITLAB_PASSWORD:-$IDE_PASSWORD}
export GIT_USERNAME=${GIT_USERNAME:-"root"}
export WORK_DIR="/tmp/gitlab-setup-$$"

print_header "GitLab Repository Creation Script"

# Configure git globally
setup_git() {
    print_step "Setting up git configuration"
    git config --global http.sslVerify false
    git config --global user.email "participants@workshops.aws"
    git config --global user.name "Workshop Participant"
    git config --global credential.helper store
    echo "https://$GIT_USERNAME:$GITLAB_PASSWORD@$(echo $GITLAB_URL | sed 's|https://||')" > ~/.git-credentials
    print_success "Git configured successfully"
}

# Function to check if repository exists and has content
check_repo_status() {
    local repo_name=$1
    local git_url="https://$GIT_USERNAME:$GITLAB_PASSWORD@$(echo $GITLAB_URL | sed 's|https://||')/$GIT_USERNAME/$repo_name.git"
    
    print_info "Checking repository: $repo_name"
    
    # Try to clone the repository to check if it exists and has content
    rm -rf "$WORK_DIR/$repo_name" 2>/dev/null || true
    mkdir -p "$WORK_DIR"
    
    if timeout 30 git clone "$git_url" "$WORK_DIR/$repo_name" 2>/dev/null; then
        local file_count=$(find "$WORK_DIR/$repo_name" -type f -not -path "*/.git/*" | wc -l)
        if [ "$file_count" -gt 1 ]; then  # More than just README
            print_success "Repository $repo_name exists and has content ($file_count files)"
            return 0  # Exists and populated
        else
            print_warning "Repository $repo_name exists but is empty"
            return 1  # Exists but needs population
        fi
    else
        print_warning "Repository $repo_name does not exist"
        return 2  # Doesn't exist
    fi
}

# Function to create repository using web form
create_repository() {
    local repo_name=$1
    local description=${2:-"Repository created by workshop script"}
    
    print_step "Creating repository: $repo_name"
    
    # Get CSRF token and login
    local csrf_token=$(curl -k -s -c "/tmp/gitlab_cookies_$$.txt" "$GITLAB_URL/users/sign_in" 2>/dev/null | grep -o 'csrf-token.*content="[^"]*"' | sed 's/.*content="\([^"]*\)".*/\1/' | head -1)
    
    if [ -z "$csrf_token" ]; then
        print_error "Failed to get CSRF token for $repo_name"
        return 1
    fi
    
    # Login
    curl -k -s -b "/tmp/gitlab_cookies_$$.txt" -c "/tmp/gitlab_cookies_$$.txt" \
        -d "authenticity_token=$csrf_token" \
        -d "user[login]=root" \
        -d "user[password]=$GITLAB_PASSWORD" \
        -d "user[remember_me]=0" \
        -X POST \
        "$GITLAB_URL/users/sign_in" > /dev/null 2>&1
    
    # Get CSRF token for project creation
    local project_csrf=$(curl -k -s -b "/tmp/gitlab_cookies_$$.txt" "$GITLAB_URL/projects/new" 2>/dev/null | grep -o 'csrf-token.*content="[^"]*"' | sed 's/.*content="\([^"]*\)".*/\1/' | head -1)
    
    if [ -n "$project_csrf" ]; then
        # Create project
        local result=$(curl -k -s -b "/tmp/gitlab_cookies_$$.txt" \
            -d "authenticity_token=$project_csrf" \
            -d "project[name]=$repo_name" \
            -d "project[path]=$repo_name" \
            -d "project[description]=$description" \
            -d "project[visibility_level]=10" \
            -d "project[initialize_with_readme]=1" \
            -X POST \
            "$GITLAB_URL/projects" 2>/dev/null)
        
        if echo "$result" | grep -q "You are being.*redirected"; then
            print_success "Repository $repo_name created successfully!"
            sleep 3  # Wait for repository to be ready
            return 0
        else
            print_error "Failed to create repository $repo_name"
            return 1
        fi
    else
        print_error "Failed to get project creation CSRF token for $repo_name"
        return 1
    fi
    
    rm -f "/tmp/gitlab_cookies_$$.txt"
}

# Function to populate application repository
populate_application_repo() {
    local repo_name=$1
    print_step "Populating application repository: $repo_name"
    
    local git_url="https://root:$GITLAB_PASSWORD@d31l55m8hkb7r3.cloudfront.net/root/$repo_name.git"
    local repo_dir="$WORK_DIR/$repo_name"
    
    # Clone repository
    rm -rf "$repo_dir" 2>/dev/null || true
    if ! timeout 30 git clone "$git_url" "$repo_dir" 2>/dev/null; then
        print_error "Failed to clone repository $repo_name"
        return 1
    fi
    
    cd "$repo_dir" || return 1
    
    # Check if application content exists
    if [ -d "${REPO_ROOT}/applications/$repo_name" ]; then
        print_info "Copying application content..."
        
        # Remove existing files except .git and README.md
        find . -maxdepth 1 -not -name '.git' -not -name '.' -not -name 'README.md' -exec rm -rf {} + 2>/dev/null || true
        
        # Copy all content from the application directory
        cp -r "${REPO_ROOT}/applications/$repo_name"/* . 2>/dev/null || true
        cp -r "${REPO_ROOT}/applications/$repo_name"/.[^.]* . 2>/dev/null || true
        
        # Add and commit changes
        git add . 2>/dev/null || true
        
        if git commit -m "Add initial application content" 2>/dev/null; then
            print_info "Content committed successfully"
            
            # Push changes
            if timeout 30 git push origin main 2>/dev/null || timeout 30 git push origin master 2>/dev/null; then
                print_success "Content pushed to $repo_name successfully!"
                return 0
            else
                print_warning "Failed to push content to $repo_name"
                return 1
            fi
        else
            print_info "No new changes to commit for $repo_name"
            return 0
        fi
    else
        print_warning "No application content found for $repo_name at ${REPO_ROOT}/applications/$repo_name"
        return 1
    fi
}

# Function to populate terraform-eks repository
populate_terraform_eks() {
    local repo_name="terraform-eks"
    print_step "Populating terraform-eks repository"
    
    local git_url="https://root:$GITLAB_PASSWORD@d31l55m8hkb7r3.cloudfront.net/root/$repo_name.git"
    local repo_dir="$WORK_DIR/$repo_name"
    
    # Clone repository
    rm -rf "$repo_dir" 2>/dev/null || true
    if ! timeout 30 git clone "$git_url" "$repo_dir" 2>/dev/null; then
        print_error "Failed to clone terraform-eks repository"
        return 1
    fi
    
    cd "$repo_dir"
    
    print_info "Copying terraform infrastructure content..."
    
    # Remove existing files except .git and README.md
    find . -maxdepth 1 -not -name '.git' -not -name '.' -not -name 'README.md' -exec rm -rf {} + 2>/dev/null || true
    
    # Copy terraform content
    cp -r "${REPO_ROOT}/platform/infra/terraform/dev" . 2>/dev/null || true
    cp -r "${REPO_ROOT}/platform/infra/terraform/prod" . 2>/dev/null || true
    cp -r "${REPO_ROOT}/platform/infra/terraform/database" . 2>/dev/null || true
    cp "${REPO_ROOT}/platform/infra/terraform/.gitignore" . 2>/dev/null || true
    cp "${REPO_ROOT}/platform/infra/terraform/create-cluster.sh" . 2>/dev/null || true
    cp "${REPO_ROOT}/platform/infra/terraform/create-database.sh" . 2>/dev/null || true
    
    git add . 2>/dev/null || true
    
    if git commit -m "Add terraform infrastructure code" 2>/dev/null; then
        print_info "Terraform content committed successfully"
        
        if timeout 30 git push origin main 2>/dev/null || timeout 30 git push origin master 2>/dev/null; then
            print_success "Terraform content pushed successfully!"
            return 0
        else
            print_warning "Failed to push terraform content"
            return 1
        fi
    else
        print_info "No new changes to commit for terraform-eks"
        return 0
    fi
}

# Function to populate platform repository
populate_platform() {
    local repo_name="platform"
    print_step "Populating platform repository"
    
    local git_url="https://root:$GITLAB_PASSWORD@d31l55m8hkb7r3.cloudfront.net/root/$repo_name.git"
    local repo_dir="$WORK_DIR/$repo_name"
    
    # Clone repository
    rm -rf "$repo_dir" 2>/dev/null || true
    if ! timeout 30 git clone "$git_url" "$repo_dir" 2>/dev/null; then
        print_error "Failed to clone platform repository"
        return 1
    fi
    
    cd "$repo_dir"
    
    print_info "Copying platform content..."
    
    # Remove existing files except .git and README.md
    find . -maxdepth 1 -not -name '.git' -not -name '.' -not -name 'README.md' -exec rm -rf {} + 2>/dev/null || true
    
    # Copy platform content
    cp -r "${REPO_ROOT}/deployment/addons/kubevela" . 2>/dev/null || true
    cp -r "${REPO_ROOT}/platform/backstage" . 2>/dev/null || true
    
    # Get the domain name for hostname replacement
    local domain_name=$(kubectl get service ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "localhost")
    
    # Replace hostname in backstage catalog file if it exists
    if [ -f "backstage/templates/catalog-info.yaml" ]; then
        sed -i "s/HOSTNAME/${domain_name}/g" backstage/templates/catalog-info.yaml
        print_info "Updated hostname in backstage catalog file to: $domain_name"
    fi
    
    git add . 2>/dev/null || true
    
    if git commit -m "Add platform configuration and backstage templates" 2>/dev/null; then
        print_info "Platform content committed successfully"
        
        if timeout 30 git push origin main 2>/dev/null || timeout 30 git push origin master 2>/dev/null; then
            print_success "Platform content pushed successfully!"
            return 0
        else
            print_warning "Failed to push platform content"
            return 1
        fi
    else
        print_info "No new changes to commit for platform"
        return 0
    fi
}

# Function to handle repository setup
setup_repository() {
    local repo_name=$1
    local repo_type=${2:-"application"}
    local description=${3:-"Repository created by workshop script"}
    
    echo
    print_info "=== Processing repository: $repo_name ==="
    
    # Use a subshell to prevent cd from affecting the main script
    (
        check_repo_status "$repo_name"
        local status=$?
        
        case $status in
            0)
                print_info "Repository $repo_name is already populated, skipping"
                return 0
                ;;
            1)
                print_info "Repository $repo_name exists but needs content"
                ;;
            2)
                print_info "Repository $repo_name needs to be created"
                if ! create_repository "$repo_name" "$description"; then
                    print_error "Failed to create repository $repo_name"
                    return 1
                fi
                ;;
        esac
        
        # Populate repository based on type
        case $repo_type in
            "application")
                populate_application_repo "$repo_name"
                ;;
            "terraform")
                populate_terraform_eks
                ;;
            "platform")
                populate_platform
                ;;
        esac
    )
    
    # Capture the exit status but don't exit the main script
    local result=$?
    if [ $result -eq 0 ]; then
        print_success "Successfully processed repository: $repo_name"
    else
        print_error "Failed to process repository: $repo_name (continuing with next repository)"
    fi
    
    return $result
}

# Cleanup function
cleanup() {
    rm -rf "$WORK_DIR" 2>/dev/null || true
    rm -f "/tmp/gitlab_cookies_$$".txt 2>/dev/null || true
}

# Set trap for cleanup
trap cleanup EXIT

# Main execution
main() {
    print_info "Starting GitLab repository setup..."
    
    # Setup git configuration
    setup_git
    
    # Create work directory
    mkdir -p "$WORK_DIR"
    
    # Track success/failure counts
    local success_count=0
    local failure_count=0
    local total_count=0
    
    # Application repositories
    print_header "Setting up Application Repositories"
    local app_repos=("dotnet" "golang" "java" "python" "next-js" "rust")
    
    for repo in "${app_repos[@]}"; do
        if [ -d "${REPO_ROOT}/applications/$repo" ]; then
            total_count=$((total_count + 1))
            if setup_repository "$repo" "application" "Sample $repo application"; then
                success_count=$((success_count + 1))
            else
                failure_count=$((failure_count + 1))
            fi
        else
            print_warning "Skipping $repo - no application content found at ${REPO_ROOT}/applications/$repo"
        fi
    done
    
    # Terraform repository
    print_header "Setting up Terraform Repository"
    total_count=$((total_count + 1))
    if setup_repository "terraform-eks" "terraform" "Terraform EKS infrastructure code"; then
        success_count=$((success_count + 1))
    else
        failure_count=$((failure_count + 1))
    fi
    
    # Platform repository
    print_header "Setting up Platform Repository"
    total_count=$((total_count + 1))
    if setup_repository "platform" "platform" "Platform configuration and Backstage templates"; then
        success_count=$((success_count + 1))
    else
        failure_count=$((failure_count + 1))
    fi
    
    echo
    print_header "Setup Summary"
    print_info "Total repositories processed: $total_count"
    print_success "Successfully processed: $success_count"
    if [ $failure_count -gt 0 ]; then
        print_error "Failed to process: $failure_count"
    fi
    
    if [ $success_count -gt 0 ]; then
        print_success "GitLab repository setup completed with $success_count successful repositories!"
        
        # Show summary
        echo
        print_header "Repository Summary"
        print_info "You can access your repositories at:"
        for repo in "${app_repos[@]}" "terraform-eks" "platform"; do
            if [ -d "${REPO_ROOT}/applications/$repo" ] || [ "$repo" = "terraform-eks" ] || [ "$repo" = "platform" ]; then
                print_info "  - $GITLAB_URL/root/$repo"
            fi
        done
    else
        print_error "No repositories were successfully processed!"
        return 1
    fi
}

# Run main function
main "$@"
