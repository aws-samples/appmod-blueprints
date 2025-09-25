#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

source $SCRIPTDIR/../scripts/utils.sh

# Main destroy function
main() {
  
  if [[ -z "${USER1_PASSWORD:-}" ]]; then
    log_error "USER1_PASSWORD environment variable is required"
    exit 1
  fi

  # Remove ArgoCD resources
  for cluster in "${CLUSTER_NAMES[@]}"; do
      if ! cleanup_kubernetes_resources_with_fallback "$cluster"; then
        log_warning "Failed to cleanup Kubernetes resources for cluster: $cluster"
        exit 1
      fi
  done

  log "Starting boostrap stack destruction..."

  # Validate backend configuration
  validate_backend_config

  export TF_VAR_resource_prefix="${RESOURCE_PREFIX:-peeks}"
  export GENERATED_TFVAR_FILE="$(mktemp).tfvars.json"
  yq eval -o=json '.' $CONFIG_FILE > $GENERATED_TFVAR_FILE

  GITLAB_DOMAIN=$(terraform -chdir=$SCRIPTDIR/gitlab_infra output -raw gitlab_domain_name)
  GITLAB_SG_ID=$(terraform -chdir=$SCRIPTDIR/gitlab_infra output -raw gitlab_security_groups)

  # Remove GitLab resources from state
  terraform state rm gitlab_personal_access_token.workshop
  terraform state rm data.gitlab_user.workshop

  # Initialize Terraform with S3 backend
  initialize_terraform "boostrap" "$SCRIPTDIR"

  # Destroy Terraform resources
  log "Destroying bootstrap resources..."
  if ! terraform -chdir=$SCRIPTDIR destroy \
    -var-file="${GENERATED_TFVAR_FILE}" \
    -var="gitlab_domain_name=${GITLAB_DOMAIN}" \
    -var="gitlab_security_groups=${GITLAB_SG_ID}" \
    -var="ide_password=${USER1_PASSWORD}" \
    -var="git_username=${GIT_USERNAME}" \
    -var="git_password=${USER1_PASSWORD}" \
    -auto-approve -refresh=false; then
    log_error "Bootstrap stack destroy failed"
    exit 1
  fi

  if ! $SKIP_GITLAB ; then
    
    initialize_terraform "gitlab infra" "$SCRIPTDIR/gitlab_infra"

    # Destroy Terraform resources
    log "Destroying gitlab infra resources..."
    if ! terraform -chdir=$SCRIPTDIR/gitlab_infra destroy \
      -var-file="${GENERATED_TFVAR_FILE}" \
      -var="git_username=${GIT_USERNAME}" \
      -var="git_password=${IDE_PASSWORD}" \
      -auto-approve; then
      log_error "Gitlab infra stack destroy failed"
      exit 1
    fi
  fi

  log_success "Bootstrap stack destroy completed successfully"
}

# Run main function
main "$@"
