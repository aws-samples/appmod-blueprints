#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

# Save the current script directory before sourcing utils.sh
DEPLOY_SCRIPTDIR="$SCRIPTDIR"
source $SCRIPTDIR/../scripts/utils.sh

# Main destroy function
main() {
  
  if [[ -z "${USER1_PASSWORD:-}" ]]; then
    log_error "USER1_PASSWORD environment variable is required"
    exit 1
  fi

  # Remove ArgoCD resources from all clusters
  for cluster in "${CLUSTER_NAMES[@]}"; do
      if ! cleanup_kubernetes_resources_with_fallback "$cluster"; then
        log_warning "Failed to cleanup Kubernetes resources for cluster: $cluster"
        exit 1
      fi
  done

  log "Starting boostrap stack destruction..."

  # Validate backend configuration
  validate_backend_config

  export GENERATED_TFVAR_FILE="$(mktemp).tfvars.json"
  yq eval -o=json '.' $CONFIG_FILE > $GENERATED_TFVAR_FILE

  if ! $SKIP_GITLAB ; then
    initialize_terraform "gitlab infra" "$DEPLOY_SCRIPTDIR/gitlab_infra" # required to fetch values from gitlab_infra
    GITLAB_DOMAIN=$(terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra output -raw gitlab_domain_name)
    GITLAB_SG_ID=$(terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra output -raw gitlab_security_groups)
  fi


  # Initialize Terraform with S3 backend
  initialize_terraform "boostrap" "$DEPLOY_SCRIPTDIR"

  cd "$DEPLOY_SCRIPTDIR" # Get into common stack directory
  # Remove GitLab resources from state, if they exist
  if ! terraform state rm gitlab_personal_access_token.workshop || ! terraform state rm data.gitlab_user.workshop; then
    log_warning "GitLab resources not found in state"
  fi
  cd - # Go back

  # Destroy Terraform resources
  log "Destroying bootstrap resources..."
  if ! terraform -chdir=$DEPLOY_SCRIPTDIR destroy \
    -var-file="${GENERATED_TFVAR_FILE}" \
    -var="gitlab_domain_name=${GITLAB_DOMAIN:-""}" \
    -var="gitlab_security_groups=${GITLAB_SG_ID:-""}" \
    -var="ide_password=${USER1_PASSWORD}" \
    -var="git_username=${GIT_USERNAME}" \
    -var="git_password=${USER1_PASSWORD}" \
    -var="working_repo=${WORKING_REPO}" \
    -auto-approve -refresh=false; then
    log_warning "Bootstrap stack destroy failed, trying again"
    if ! terraform -chdir=$DEPLOY_SCRIPTDIR destroy \
      -var-file="${GENERATED_TFVAR_FILE}" \
      -var="gitlab_domain_name=${GITLAB_DOMAIN:-""}" \
      -var="gitlab_security_groups=${GITLAB_SG_ID:-""}" \
      -var="ide_password=${USER1_PASSWORD}" \
      -var="git_username=${GIT_USERNAME}" \
      -var="git_password=${USER1_PASSWORD}" \
      -var="working_repo=${WORKING_REPO}" \
      -auto-approve -refresh=false; then
      log_error "Bootstrap stack destroy failed again, exiting"
      exit 1
    fi
  fi

  if ! $SKIP_GITLAB ; then
    
    initialize_terraform "gitlab infra" "$DEPLOY_SCRIPTDIR/gitlab_infra"

    # Destroy Terraform resources
    log "Destroying gitlab infra resources..."
    if ! terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra destroy \
      -var-file="${GENERATED_TFVAR_FILE}" \
      -var="git_username=${GIT_USERNAME}" \
      -var="git_password=${IDE_PASSWORD}" \
      -var="working_repo=${WORKING_REPO}" \
      -auto-approve; then
      log_warning "Gitlab infra stack destroy failed, trying one more time"
      if ! terraform -chdir=$DEPLOY_SCRIPTDIR/gitlab_infra destroy \
        -var-file="${GENERATED_TFVAR_FILE}" \
        -var="git_username=${GIT_USERNAME}" \
        -var="git_password=${IDE_PASSWORD}" \
        -var="working_repo=${WORKING_REPO}" \
        -auto-approve; then
        log_error "Gitlab infra stack destroy failed again, exiting"
        exit 1
      fi
    fi
  fi

  log_success "Bootstrap stack destroy completed successfully"
}

# Run main function
main "$@"
