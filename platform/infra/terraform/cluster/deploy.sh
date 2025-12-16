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


# Check for Identity Center configuration
check_identity_center() {
  # Try to get IDC instance ARN from AWS API if env var not set
  if [[ -z "${TF_VAR_identity_center_instance_arn:-}" ]]; then
    log "🔍 Checking for Identity Center instance..."
    
    # Get IDC instance ARN from AWS API
    IDC_INSTANCE_ARN=$(aws sso-admin list-instances --query 'Instances[0].InstanceArn' --output text 2>/dev/null || echo "None")
    
    if [[ "$IDC_INSTANCE_ARN" != "None" && -n "$IDC_INSTANCE_ARN" ]]; then
      export TF_VAR_identity_center_instance_arn="$IDC_INSTANCE_ARN"
      log "📋 Found Identity Center instance: $IDC_INSTANCE_ARN"
      
      # Try to get group IDs from terraform outputs if identity-center module was deployed
      if [[ -d "../identity-center" ]]; then
        cd ../identity-center
        if terraform show -json > /dev/null 2>&1; then
          export TF_VAR_identity_center_admin_group_id=$(terraform output -raw admin_group_id 2>/dev/null || echo "")
          export TF_VAR_identity_center_developer_group_id=$(terraform output -raw developer_group_id 2>/dev/null || echo "")
          log "📋 Retrieved Identity Center group IDs from terraform state"
        fi
        cd - > /dev/null
      fi
    else
      log "ℹ️  No Identity Center instance found"
    fi
  fi

  if [[ -n "${TF_VAR_identity_center_instance_arn:-}" ]]; then
    log "✅ Identity Center configuration detected"
    log "   Instance ARN: ${TF_VAR_identity_center_instance_arn}"
    log "   Admin Group: ${TF_VAR_identity_center_admin_group_id:-not set}"
    log "   Developer Group: ${TF_VAR_identity_center_developer_group_id:-not set}"
  else
    log "⚠️  Identity Center not configured - EKS Capabilities will be created without SSO"
    log "   To enable SSO, run: cd ../identity-center && ./deploy.sh"
  fi
}

# Main deployment function
main() {
  log "Starting clusters stack deployment..."
  check_identity_center

  if [ -z "$HUB_VPC_ID" ] || [ -z "$HUB_SUBNET_IDS" ]; then
    log_error "HUB_VPC_ID and HUB_SUBNET_IDS environment variables should be set"
    exit 1
  fi

  # Validate backend configuration
  validate_backend_config

  # Set Terraform variables from environment
  export GENERATED_TFVAR_FILE="$(mktemp).tfvars.json"
  yq eval -o=json '.' $CONFIG_FILE > $GENERATED_TFVAR_FILE

  # Initialize Terraform with S3 backend
  initialize_terraform "clusters" "$DEPLOY_SCRIPTDIR"
  
  # Apply Terraform configuration
  log "Applying clusters stack..."
  if ! terraform -chdir=$DEPLOY_SCRIPTDIR apply \
    -var-file="${GENERATED_TFVAR_FILE}" \
    -var="hub_vpc_id=${HUB_VPC_ID}" \
    -var="hub_subnet_ids=$(echo "${HUB_SUBNET_IDS}" | sed "s/'/\"/g")" \
    -var="resource_prefix=${RESOURCE_PREFIX}" \
    -var="workshop_participant_role_arn=${WS_PARTICIPANT_ROLE_ARN}" \
    -parallelism=3 -auto-approve; then
    log_warning "Terraform apply for clusters stack failed, trying again..."
    if ! terraform -chdir=$DEPLOY_SCRIPTDIR apply \
      -var-file="${GENERATED_TFVAR_FILE}" \
      -var="hub_vpc_id=${HUB_VPC_ID}" \
      -var="hub_subnet_ids=$(echo "${HUB_SUBNET_IDS}" | sed "s/'/\"/g")" \
      -var="resource_prefix=${RESOURCE_PREFIX}" \
      -var="workshop_participant_role_arn=${WS_PARTICIPANT_ROLE_ARN}" \
      -parallelism=3 -auto-approve; then
      log_error "Terraform apply for clusters stack failed again, exiting"
      exit 1
    fi
  fi

  log_success "Clusters stack deployment completed successfully"
}

# Run main function
main "$@"
