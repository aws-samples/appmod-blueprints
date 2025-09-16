#!/bin/bash

# Exit on error
set -e

# Source all environment files in .bashrc.d
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        if [ -f "$file" ]; then
            source "$file"
        fi
    done
fi

# Source colors for output formatting
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

print_header "Updating Backstage Template Defaults"

# Define base paths
TEMPLATES_BASE_PATH="/home/ec2-user/environment/platform-on-eks-workshop/platform/backstage/templates"

# Get environment-specific values
GITLAB_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, 'gitlab')].DomainName | [0]" --output text)
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
if [ -z "$AWS_ACCOUNT_ID" ]; then
  print_error "AWS_ACCOUNT_ID environment variable is not set"
  exit 1
fi

if [ -z "$AWS_REGION" ]; then
  print_error "AWS_REGION environment variable is not set"
  exit 1
fi

print_info "Using the following values for template updates:"
echo "  Account ID: $AWS_ACCOUNT_ID"
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
    yq -i '.spec.parameters[0].properties.accountId.default = "'$AWS_ACCOUNT_ID'"' "$template_path"
    yq -i '.spec.parameters[0].properties.managementAccountId.default = "'$AWS_ACCOUNT_ID'"' "$template_path"
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

# Function to update all templates (now just validates they exist)
update_all_templates() {
    print_step "Validating all template files"
    
    # Find all template directories and process them
    for template_dir in "$TEMPLATES_BASE_PATH"/*/; do
        if [ -d "$template_dir" ]; then
            local template_name=$(basename "$template_dir")
            local template_path="$template_dir/template.yaml"
            
            # Handle different template file naming patterns
            if [ ! -f "$template_path" ]; then
                # Try common alternative naming patterns
                for alt_name in "template-$template_name.yaml" "template-*.yaml"; do
                    local alt_path="$template_dir/$alt_name"
                    if [ -f "$alt_path" ] || ls $alt_path 1> /dev/null 2>&1; then
                        template_path=$(ls "$template_dir"/template-*.yaml 2>/dev/null | head -1)
                        break
                    fi
                done
            fi
            
            if [ -f "$template_path" ]; then
                print_info "✓ Found template: $template_name"
                
                # Check if the template has fetchSystem step
                if yq -e '.spec.steps[] | select(.id == "fetchSystem")' "$template_path" > /dev/null 2>&1; then
                    print_info "  - Has fetchSystem step"
                fi
            else
                print_warning "✗ No template file found in $template_name directory"
            fi
        fi
    done
    
    print_success "Template validation completed"
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
            yq -i '.spec.parameters[].properties.accountId.default = "'$AWS_ACCOUNT_ID'"' "$template_path"
            print_info "Updated Account ID in $template_name template"
        fi
        

        
        print_success "$template_name template updated"
    done
}

# Function to update system-info entity
update_system_info() {
    local catalog_info_path="$TEMPLATES_BASE_PATH/catalog-info.yaml"
    
    if [ ! -f "$catalog_info_path" ]; then
        print_warning "catalog-info.yaml not found at $catalog_info_path"
        return
    fi
    
    print_step "Updating system-info entity hostname"
    
    # Update the hostname in the system-info entity
    yq -i '(.spec.hostname) = "'$GITLAB_DOMAIN'"' "$catalog_info_path"
    
    print_success "Updated system-info hostname to $GITLAB_DOMAIN"
}



# Function to stage template files
stage_template_files() {
    print_step "Staging template files"
    git add "$TEMPLATES_BASE_PATH/"
    print_success "Staged all files in $TEMPLATES_BASE_PATH/"
}

# Main execution
print_info "Starting template updates..."

# Update all template types
update_eks_cluster_template
update_dev_prod_env_template
update_all_templates
update_aws_resource_templates
update_system_info

# Stage the modified template files
stage_template_files

print_success "All Backstage templates have been updated with environment-specific values!"

print_info "Updated templates with:"
echo "  ✓ Account ID: $AWS_ACCOUNT_ID"
echo "  ✓ AWS Region: $AWS_REGION"
echo "  ✓ GitLab Domain: $GITLAB_DOMAIN"
echo "  ✓ Repository URLs: Updated to use actual GitLab domain"
echo "  ✓ Ingress Domain: $INGRESS_DOMAIN_NAME"

print_info "Templates are now ready for use in Backstage!"
