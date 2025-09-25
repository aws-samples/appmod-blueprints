#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

source $SCRIPTDIR/../scripts/utils.sh

# Main deployment function
main() {
  log "Starting bootstrap stack deployment..."

  if [[ -z "${USER1_PASSWORD:-}" ]]; then
    log_error "USER1_PASSWORD environment variable is required"
    exit 1
  fi
  # Validate backend configuration
  validate_backend_config

  export GENERATED_TFVAR_FILE="$(mktemp).tfvars.json"
  yq eval -o=json '.' $CONFIG_FILE > $GENERATED_TFVAR_FILE

  if ! $SKIP_GITLAB ; then
    # Initialize Terraform with S3 backend
    initialize_terraform "gitlab infra" "$SCRIPTDIR/gitlab_infra"
    
    # Apply Terraform configuration
    log "Applying gitlab infra resources..."
    if ! terraform -chdir=$SCRIPTDIR/gitlab_infra apply \
      -var-file="${GENERATED_TFVAR_FILE}" \
      -var="git_username=${GIT_USERNAME}" \
      -var="git_password=${USER1_PASSWORD}" \
      -parallelism=3 -auto-approve; then
      log_error "Terraform apply failed for gitlab infra stack"
      exit 1
    fi
  fi

  GITLAB_DOMAIN=$(terraform -chdir=$SCRIPTDIR/gitlab_infra output -raw gitlab_domain_name)
  GITLAB_SG_ID=$(terraform -chdir=$SCRIPTDIR/gitlab_infra output -raw gitlab_security_groups)
  # Initialize Terraform with S3 backend
  initialize_terraform "bootstrap" "$SCRIPTDIR"
  
  # Apply Terraform configuration
  log "Applying bootstrap resources..."
  if ! terraform -chdir=$SCRIPTDIR apply \
    -var-file="${GENERATED_TFVAR_FILE}" \
    -var="gitlab_domain_name=${GITLAB_DOMAIN}" \
    -var="gitlab_security_groups=${GITLAB_SG_ID}" \
    -var="ide_password=${USER1_PASSWORD}" \
    -var="git_username=${GIT_USERNAME}" \
    -var="git_password=${USER1_PASSWORD}" \
    -var="resource_prefix=${RESOURCE_PREFIX}" \
    -parallelism=3 -auto-approve; then
    log_error "Terraform apply failed for bootstrap stack"
    exit 1
  fi
  
  log_success "Cootstrap stack deployment completed successfully"
}

# Run main function
main "$@"
