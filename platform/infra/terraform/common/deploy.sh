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

  if [[ -z "${USER1_PASSWORD:-}" ]]; then
    log_error "USER1_PASSWORD environment variable is required"
    exit 1
  fi
  # Validate backend configuration
  validate_backend_config

  # Update config file cluster regions if WORKSHOP_CLUSTERS
  if [[ "$WORKSHOP_CLUSTERS" == "true" ]]; then
    log "Updating config file cluster regions..."
    TEMP_CONFIG_FILE="$(mktemp).yaml"
    cp "$CONFIG_FILE" "$TEMP_CONFIG_FILE"
    yq eval '.clusters[].region = env(AWS_REGION)' -i "$TEMP_CONFIG_FILE"
    CONFIG_FILE="$TEMP_CONFIG_FILE"
  fi

  export GENERATED_TFVAR_FILE="$(mktemp).tfvars.json"
  yq eval -o=json '.' $CONFIG_FILE > $GENERATED_TFVAR_FILE

  if ! $SKIP_GITLAB ; then
    # Initialize Terraform with S3 backend
    initialize_terraform "gitlab infra" "$DEPLOY_SCRIPTDIR/gitlab_infra"
    
    # Apply Terraform configuration
    log "Applying gitlab infra resources..."
    if ! terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra apply \
      -var-file="${GENERATED_TFVAR_FILE}" \
      -var="git_username=${GIT_USERNAME}" \
      -var="git_password=${USER1_PASSWORD}" \
      -var="working_repo=${WORKING_REPO}" \
      -parallelism=3 -auto-approve; then
      log_error "Terraform apply failed for gitlab infra stack"
      exit 1
    fi

    export GITLAB_DOMAIN=$(terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra output -raw gitlab_domain_name)
    GITLAB_SG_ID=$(terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra output -raw gitlab_security_groups)

    # Update backstage default values
    update_backstage_defaults
    # Push repo to Gitlab
    gitlab_repository_setup
  fi

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
    log_error "Terraform apply failed for bootstrap stack"
    exit 1
  fi
  
  log_success "Cootstrap stack deployment completed successfully"
}

# Run main function
main "$@"
