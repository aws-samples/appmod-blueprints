#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

# Save the current script directory before sourcing utils.sh
DEPLOY_SCRIPTDIR="$SCRIPTDIR"
source $SCRIPTDIR/../scripts/utils.sh

# Check if clusters are created through Workshop
export WORKSHOP_CLUSTERS=${WORKSHOP_CLUSTERS:-false}

# Main deployment function
main() {
  log "Starting bootstrap stack deployment..."

  if [[ -z "${USER1_PASSWORD:-${USER_PASSWORD:-}}" ]]; then
    log_error "USER1_PASSWORD environment variable is required"
    exit 1
  fi

    # Configure kubectl access to use kubectl in terraform external resources
  for cluster in "${CLUSTER_NAMES[@]}"; do
    if ! kubectl get nodes --request-timeout=10s --context $cluster &>/dev/null; then
      log_warning "kubectl cannot connect to cluster, setting up kubectl access"
      configure_kubectl_with_fallback "$cluster" || {
        log_error "kubectl configuration failed, cannot proceed with bootstrap"
        exit 1
      }
    fi
    log_success "kubectl is working for $cluster, proceeding..."
  done
  
  # Validate backend configuration
  validate_backend_config

  export GENERATED_TFVAR_FILE="$(mktemp).tfvars.json"
  yq eval -o=json '.' $CONFIG_FILE > $GENERATED_TFVAR_FILE

  if ! $SKIP_GITLAB ; then
    # Initialize Terraform with S3 backend
    initialize_terraform "gitlab infra" "$DEPLOY_SCRIPTDIR/gitlab_infra"
    
    # Apply Terraform configuration with retry logic
    log "Applying gitlab infra resources..."
    
    # Retry function with exponential backoff
    retry_terraform_apply() {
      local max_attempts=3
      local attempt=1
      local delay=30
      
      while [ $attempt -le $max_attempts ]; do
        log "Attempt $attempt of $max_attempts for gitlab infra stack..."
        
        if terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra apply \
          -var-file="${GENERATED_TFVAR_FILE}" \
          -var="git_username=${GIT_USERNAME}" \
          -var="git_password=${USER1_PASSWORD}" \
          -var="working_repo=${WORKING_REPO}" \
          -parallelism=3 -auto-approve; then
          log_success "Terraform apply succeeded on attempt $attempt"
          return 0
        fi
        
        if [ $attempt -eq $max_attempts ]; then
          log_error "Terraform apply failed after $max_attempts attempts"
          return 1
        fi
        
        log_warning "Attempt $attempt failed, waiting ${delay}s before retry..."
        sleep $delay
        delay=$((delay * 2))  # Exponential backoff
        attempt=$((attempt + 1))
      done
    }
    
    if ! retry_terraform_apply; then
      exit 1
    fi
  fi

  # Get gitlab cloudfront domain from gitlab infra stack
  export GITLAB_DOMAIN=$(terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra output -raw gitlab_domain_name)
  GITLAB_SG_ID=$(terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra output -raw gitlab_security_groups)

  # Create spoke cluster secret values
  create_spoke_cluster_secret_values

  # Push repo to Gitlab
  gitlab_repository_setup
  
  # Initialize Terraform with S3 backend
  initialize_terraform "bootstrap" "$DEPLOY_SCRIPTDIR"
  
  # Apply Terraform configuration
  log "Applying bootstrap resources..."
  if ! terraform -chdir=$DEPLOY_SCRIPTDIR apply \
    -var-file="${GENERATED_TFVAR_FILE}" \
    -var="gitlab_domain_name=${GITLAB_DOMAIN:-""}" \
    -var="gitlab_security_groups=${GITLAB_SG_ID:-""}" \
    -var="ide_password=${USER1_PASSWORD}" \
    -var="git_username=${GIT_USERNAME}" \
    -var="git_password=${USER1_PASSWORD}" \
    -var="resource_prefix=${RESOURCE_PREFIX}" \
    -var="working_repo=${WORKING_REPO}" \
    -parallelism=3 -auto-approve; then
    log_warning "Terraform apply failed for bootstrap stack, trying again..."
    if ! terraform -chdir=$DEPLOY_SCRIPTDIR apply \
      -var-file="${GENERATED_TFVAR_FILE}" \
      -var="gitlab_domain_name=${GITLAB_DOMAIN:-""}" \
      -var="gitlab_security_groups=${GITLAB_SG_ID:-""}" \
      -var="ide_password=${USER1_PASSWORD}" \
      -var="git_username=${GIT_USERNAME}" \
      -var="git_password=${USER1_PASSWORD}" \
      -var="resource_prefix=${RESOURCE_PREFIX}" \
      -var="working_repo=${WORKING_REPO}" \
      -parallelism=3 -auto-approve; then
      log_error "Terraform apply failed for bootstrap stack again, exiting"
      exit 1
    fi
  fi

  # Get ArgoCD domain from Terraform output
  export ARGOCD_DOMAIN=$(terraform -chdir=$DEPLOY_SCRIPTDIR output -raw ingress_domain_name)

  # Update backstage default values now that both domains are available
  update_backstage_defaults
  
  # Push repo to Gitlab
  gitlab_repository_setup
  
  log_success "Bootstrap stack deployment completed successfully"
}

# Run main function
main "$@"
