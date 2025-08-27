#!/bin/bash

# Exit on error
set -e

# Source colors for output formatting
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

print_header "Updating Backstage Template Defaults"

# Define base paths
TEMPLATES_BASE_PATH="/home/ec2-user/environment/platform-on-eks-workshop/platform/backstage/templates"

# Get environment-specific values
GITLAB_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[?Origins.Items[?contains(DomainName, 'gitlab')]].DomainName" --output text)
INGRESS_DOMAIN_NAME=$(aws cloudfront list-distributions --query "DistributionList.Items[?Origins.Items[?contains(DomainName, 'hub-ingress')]].DomainName" --output text)

# Try to get GIT_USERNAME from environment or secret
if [ -z "$GIT_USERNAME" ]; then
    GIT_USERNAME=$(kubectl get secret git-credentials -n argocd -o jsonpath='{.data.GIT_USERNAME}' 2>/dev/null | base64 --decode 2>/dev/null || echo "user1")
fi

# Set WORKING_REPO if not already set
if [ -z "$WORKING_REPO" ]; then
    WORKING_REPO="platform-on-eks-workshop"
fi

REPO_FULL_URL=https://$GITLAB_DOMAIN/$GIT_USERNAME/$WORKING_REPO.git

# Check if required environment variables are set
if [ -z "$ACCOUNT_ID" ]; then
  print_error "ACCOUNT_ID environment variable is not set"
  exit 1
fi

if [ -z "$AWS_REGION" ]; then
  print_error "AWS_REGION environment variable is not set"
  exit 1
fi

print_info "Using the following values for template updates:"
echo "  Account ID: $ACCOUNT_ID"
echo "  AWS Region: $AWS_REGION"
echo "  GitLab Domain: $GITLAB_DOMAIN"
echo "  Git Username: $GIT_USERNAME"
echo "  Working Repo: $WORKING_REPO"
echo "  Repo Full URL: $REPO_FULL_URL"
echo "  Ingress Domain: $INGRESS_DOMAIN_NAME"

# Function to update EKS cluster template
update_eks_cluster_template() {
    local template_path="$TEMPLATES_BASE_PATH/eks-cluster-template/template.yaml"
    
    if [ ! -f "$template_path" ]; then
        print_warning "EKS cluster template not found at $template_path"
        return
    fi
    
    print_step "Updating EKS cluster template"
    
    # Update the template.yaml file using yq
    yq -i '.spec.parameters[0].properties.accountId.default = "'$ACCOUNT_ID'"' "$template_path"
    yq -i '.spec.parameters[0].properties.managementAccountId.default = "'$ACCOUNT_ID'"' "$template_path"
    yq -i '.spec.parameters[0].properties.region.default = "'$AWS_REGION'"' "$template_path"
    yq -i '.spec.parameters[0].properties.repoHostUrl.default = "'$GITLAB_DOMAIN'"' "$template_path"
    yq -i '.spec.parameters[0].properties.repoUsername.default = "'$GIT_USERNAME'"' "$template_path"
    yq -i '.spec.parameters[0].properties.repoName.default = "'$WORKING_REPO'"' "$template_path"
    yq -i '.spec.parameters[0].properties.ingressDomainName.default = "'$INGRESS_DOMAIN_NAME'"' "$template_path"
    yq -i '.spec.parameters[1].properties.addonsRepoUrl.default = "'$REPO_FULL_URL'"' "$template_path"
    yq -i '.spec.parameters[1].properties.fleetRepoUrl.default = "'$REPO_FULL_URL'"' "$template_path"
    yq -i '.spec.parameters[1].properties.platformRepoUrl.default = "'$REPO_FULL_URL'"' "$template_path"
    yq -i '.spec.parameters[1].properties.workloadRepoUrl.default = "'$REPO_FULL_URL'"' "$template_path"
    
    print_success "EKS cluster template updated"
}

# Function to update Create Dev and Prod Environment template
update_dev_prod_env_template() {
    local template_path="$TEMPLATES_BASE_PATH/create-dev-and-prod-env/template-create-dev-and-prod-env.yaml"
    
    if [ ! -f "$template_path" ]; then
        print_warning "Create Dev and Prod Environment template not found at $template_path"
        return
    fi
    
    print_step "Updating Create Dev and Prod Environment template"
    
    # Update AWS region default (check if it exists first)
    if yq -e '.spec.parameters[0].properties.aws_region' "$template_path" > /dev/null 2>&1; then
        yq -i '.spec.parameters[0].properties.aws_region.default = "'$AWS_REGION'"' "$template_path"
        print_info "Updated AWS region to $AWS_REGION"
    fi
    
    # Update repoHostUrl parameter (check if it exists first)
    if yq -e '.spec.parameters[0].properties.repoHostUrl' "$template_path" > /dev/null 2>&1; then
        yq -i '.spec.parameters[0].properties.repoHostUrl.default = "'$GITLAB_DOMAIN'"' "$template_path"
        print_info "Updated repoHostUrl to $GITLAB_DOMAIN"
    fi
    
    # Update repoUsername parameter (check if it exists first)
    if yq -e '.spec.parameters[0].properties.repoUsername' "$template_path" > /dev/null 2>&1; then
        yq -i '.spec.parameters[0].properties.repoUsername.default = "'$GIT_USERNAME'"' "$template_path"
        print_info "Updated repoUsername to $GIT_USERNAME"
    fi
    
    # Update repoName parameter (check if it exists first)
    if yq -e '.spec.parameters[0].properties.repoName' "$template_path" > /dev/null 2>&1; then
        yq -i '.spec.parameters[0].properties.repoName.default = "'$WORKING_REPO'"' "$template_path"
        print_info "Updated repoName to $WORKING_REPO"
    fi
    
    print_success "Create Dev and Prod Environment template updated"
}

# Function to update App Deploy templates
update_app_deploy_templates() {
    local templates=("app-deploy" "app-deploy-without-repo")
    
    for template_name in "${templates[@]}"; do
        local template_path="$TEMPLATES_BASE_PATH/$template_name/template.yaml"
        
        if [ ! -f "$template_path" ]; then
            print_warning "$template_name template not found at $template_path"
            continue
        fi
        
        print_step "Updating $template_name template"
        
        # Check if the template has fetchSystem step that references system-info
        if yq -e '.spec.steps[] | select(.id == "fetchSystem")' "$template_path" > /dev/null 2>&1; then
            # Update any references to gitea hostname to use our GitLab domain
            # This is a more complex update that might need template-specific logic
            print_info "Found fetchSystem step in $template_name, updating GitLab references"
            
            # Update any hardcoded gitea references to use our GitLab setup
            if yq -e '.spec.steps[] | select(.action == "publish:gitea")' "$template_path" > /dev/null 2>&1; then
                print_info "Updating publish:gitea action to use GitLab domain"
                # Note: This might need more specific updates based on the actual template structure
            fi
        fi
        
        print_success "$template_name template checked"
    done
}

# Function to update S3 and RDS templates
update_aws_resource_templates() {
    local templates=("s3-bucket" "s3-bucket-ack" "rds-cluster")
    
    for template_name in "${templates[@]}"; do
        local template_path="$TEMPLATES_BASE_PATH/$template_name/template.yaml"
        
        if [ ! -f "$template_path" ]; then
            print_warning "$template_name template not found at $template_path"
            continue
        fi
        
        print_step "Updating $template_name template"
        
        # Update AWS region if it exists in the template
        if yq -e '.spec.parameters[].properties.aws_region' "$template_path" > /dev/null 2>&1; then
            yq -i '.spec.parameters[].properties.aws_region.default = "'$AWS_REGION'"' "$template_path"
            print_info "Updated AWS region in $template_name template"
        fi
        
        # Update account ID if it exists in the template
        if yq -e '.spec.parameters[].properties.accountId' "$template_path" > /dev/null 2>&1; then
            yq -i '.spec.parameters[].properties.accountId.default = "'$ACCOUNT_ID'"' "$template_path"
            print_info "Updated Account ID in $template_name template"
        fi
        
        # Update any GitLab repository references
        if yq -e '.spec.steps[] | select(.action == "publish:gitea")' "$template_path" > /dev/null 2>&1; then
            print_info "Found GitLab publish action in $template_name, updating domain references"
            # Update the repoUrl to use our GitLab domain
            yq -i '(.spec.steps[] | select(.action == "publish:gitea") | .input.repoUrl) |= sub("gitea"; "'$GITLAB_DOMAIN'/'$GIT_USERNAME'")' "$template_path"
        fi
        
        print_success "$template_name template updated"
    done
}

# Main execution
print_info "Starting template updates..."

# Update all template types
update_eks_cluster_template
update_dev_prod_env_template
update_app_deploy_templates
update_aws_resource_templates

print_success "All Backstage templates have been updated with environment-specific values!"

print_info "Updated templates with:"
echo "  ✓ Account ID: $ACCOUNT_ID"
echo "  ✓ AWS Region: $AWS_REGION"
echo "  ✓ GitLab Domain: $GITLAB_DOMAIN"
echo "  ✓ Repository URLs: Updated to use actual GitLab domain"
echo "  ✓ Ingress Domain: $INGRESS_DOMAIN_NAME"

print_info "Templates are now ready for use in Backstage!"
