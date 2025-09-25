#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

DEPLOY_SCRIPTDIR="$SCRIPTDIR"
source $SCRIPTDIR/../scripts/utils.sh

# Main destroy function
main() {
  log "Starting clusters stack destruction..."
  
  if [ -z "$HUB_VPC_ID" ] || [ -z "$HUB_SUBNET_IDS" ]; then
    log_error "HUB_VPC_ID and HUB_SUBNET_IDS environment variables should be set"
    exit 1
  fi

  # Validate backend configuration
  validate_backend_config

  export GENERATED_TFVAR_FILE="$(mktemp).tfvars.json"
  yq eval -o=json '.' $CONFIG_FILE > $GENERATED_TFVAR_FILE


  # Initialize Terraform with S3 backend
  initialize_terraform "clusters" "$DEPLOY_SCRIPTDIR"

  # Destroy Terraform resources
  log "Destroying clusters stack..."
  if ! terraform -chdir=$DEPLOY_SCRIPTDIR destroy \
    -var-file="${GENERATED_TFVAR_FILE}" \
    -var="hub_vpc_id=${HUB_VPC_ID}" \
    -var="hub_subnet_ids=${HUB_SUBNET_IDS}" \
    -var="resource_prefix=${RESOURCE_PREFIX}" \
    -var="is_workshop=${IS_WS}" \
    -var="workshop_participant_role_arn=${WS_PARTICIPANT_ROLE_ARN}" \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="region=${AWS_REGION}" \
    -auto-approve; then
    log_error "Clusters stack destroy failed..."
    exit 1
  fi

  log_success "Clusters stack destroy completed successfully"
}

# Run main function
main "$@"
