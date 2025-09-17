#!/bin/bash

# Simple GitLab repository creation script for individual repositories
# Usage: ./create-single-repo.sh <repo-name>

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

# Get environment variables
export GITLAB_URL=${GITLAB_URL:-$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, 'gitlab')].DomainName | [0]" --output text | sed 's/^/https:\/\//')}
export GITLAB_PASSWORD=${GITLABPW:-$IDE_PASSWORD}
export GIT_USERNAME=${GIT_USERNAME:-"user1"}

if [ -z "$1" ]; then
    print_error "Usage: $0 <repo-name>"
    exit 1
fi

REPO_NAME="$1"

print_header "Creating GitLab Repository: $REPO_NAME"

# Create repository using web form
create_repository() {
    local repo_name=$1
    
    print_step "Creating repository: $repo_name"
    
    # Get CSRF token and login
    local csrf_token=$(curl -k -s -c "/tmp/gitlab_cookies_$$.txt" "$GITLAB_URL/users/sign_in" 2>/dev/null | grep -o 'csrf-token.*content="[^"]*"' | sed 's/.*content="\([^"]*\)".*/\1/' | head -1)
    
    if [ -z "$csrf_token" ]; then
        print_error "Failed to get CSRF token for $repo_name"
        return 1
    fi
    
    print_info "Got CSRF token: ${csrf_token:0:10}..."
    
    # Login
    print_info "Logging in as $GIT_USERNAME..."
    curl -k -s -b "/tmp/gitlab_cookies_$$.txt" -c "/tmp/gitlab_cookies_$$.txt" \
        -d "authenticity_token=$csrf_token" \
        -d "user[login]=$GIT_USERNAME" \
        -d "user[password]=$GITLAB_PASSWORD" \
        -d "user[remember_me]=0" \
        -X POST \
        "$GITLAB_URL/users/sign_in" > /dev/null 2>&1
    
    # Get CSRF token for project creation
    local project_csrf=$(curl -k -s -b "/tmp/gitlab_cookies_$$.txt" "$GITLAB_URL/projects/new" 2>/dev/null | grep -o 'csrf-token.*content="[^"]*"' | sed 's/.*content="\([^"]*\)".*/\1/' | head -1)
    
    if [ -n "$project_csrf" ]; then
        print_info "Got project CSRF token: ${project_csrf:0:10}..."
        
        # Create project
        local result=$(curl -k -s -b "/tmp/gitlab_cookies_$$.txt" \
            -d "authenticity_token=$project_csrf" \
            -d "project[name]=$repo_name" \
            -d "project[path]=$repo_name" \
            -d "project[description]=Repository created by Backstage template" \
            -d "project[visibility_level]=10" \
            -d "project[initialize_with_readme]=1" \
            -X POST \
            "$GITLAB_URL/projects" 2>/dev/null)
        
        if echo "$result" | grep -q "You are being.*redirected"; then
            print_success "Repository $repo_name created successfully!"
            print_info "Repository URL: $GITLAB_URL/$GIT_USERNAME/$repo_name"
            sleep 3  # Wait for repository to be ready
            return 0
        else
            print_error "Failed to create repository $repo_name"
            print_info "Response preview: $(echo "$result" | head -c 200)..."
            return 1
        fi
    else
        print_error "Failed to get project creation CSRF token for $repo_name"
        return 1
    fi
    
    rm -f "/tmp/gitlab_cookies_$$.txt"
}

# Create the repository
if create_repository "$REPO_NAME"; then
    print_success "Repository creation completed successfully!"
    exit 0
else
    print_error "Repository creation failed!"
    exit 1
fi
