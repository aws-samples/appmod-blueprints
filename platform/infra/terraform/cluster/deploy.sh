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

cd $SCRIPTDIR

# Check for Identity Center configuration
check_identity_center() {
  # Try to get outputs from identity-center module if env vars not set
  if [[ -z "${TF_VAR_identity_center_instance_arn:-}" ]] && [[ -d "../identity-center" ]]; then
    log "🔍 Checking for Identity Center outputs..."
    cd ../identity-center
    
    # Initialize terraform with S3 backend if not already initialized
    if [[ ! -d ".terraform" ]]; then
      log "Initializing identity-center terraform state..."
      initialize_terraform "identity-center" "$(pwd)"
    fi
    
    if terraform show -json > /dev/null 2>&1; then
      export TF_VAR_identity_center_instance_arn=$(terraform output -raw instance_arn 2>/dev/null || echo "")
      export TF_VAR_identity_center_admin_group_id=$(terraform output -raw admin_group_id 2>/dev/null || echo "")
      export TF_VAR_identity_center_developer_group_id=$(terraform output -raw developer_group_id 2>/dev/null || echo "")
      log "📥 Auto-loaded Identity Center configuration from terraform outputs"
    fi
    cd - > /dev/null
  fi

  # If still not set, try to get IDC instance ARN from AWS API
  if [[ -z "${TF_VAR_identity_center_instance_arn:-}" ]]; then
    log "🔍 Checking for Identity Center instance via AWS API..."
    
    # Get IDC instance ARN from AWS API
    IDC_INSTANCE_ARN=$(aws sso-admin list-instances --query 'Instances[0].InstanceArn' --output text 2>/dev/null | head -1 | tr -d '\n' || echo "")
    
    if [[ -n "$IDC_INSTANCE_ARN" && "$IDC_INSTANCE_ARN" != "None" && "$IDC_INSTANCE_ARN" =~ ^arn:aws:sso ]]; then
      export TF_VAR_identity_center_instance_arn="$IDC_INSTANCE_ARN"
      log "📋 Found Identity Center instance: $IDC_INSTANCE_ARN"
    fi
  fi

  # Validate Identity Center configuration is complete
  if [[ -z "${TF_VAR_identity_center_instance_arn:-}" ]]; then
    log_error "❌ Identity Center instance ARN is required for EKS ArgoCD capability"
    log_error "Please deploy Identity Center first:"
    log_error "  cd ../identity-center && ./deploy.sh"
    exit 1
  fi

  if [[ -z "${TF_VAR_identity_center_admin_group_id:-}" ]] || [[ -z "${TF_VAR_identity_center_developer_group_id:-}" ]]; then
    log_error "❌ Identity Center groups are required for EKS ArgoCD capability"
    log_error "Please deploy Identity Center first:"
    log_error "  cd ../identity-center && ./deploy.sh"
    exit 1
  fi

  log "✅ Identity Center configuration validated"
  log "   Instance ARN: ${TF_VAR_identity_center_instance_arn}"
  log "   Admin Group: ${TF_VAR_identity_center_admin_group_id}"
  log "   Developer Group: ${TF_VAR_identity_center_developer_group_id}"
}

# Main deployment function
main() {
  log "Starting clusters stack deployment..."
  check_identity_center

  if [ -z "$HUB_VPC_ID" ] || [ -z "$HUB_SUBNET_IDS" ]; then
    log_error "HUB_VPC_ID and HUB_SUBNET_IDS environment variables should be set"
    exit 1
  fi

  # Fix HUB_SUBNET_IDS format if it doesn't have single quotes
  if [[ "$HUB_SUBNET_IDS" =~ ^\[subnet- ]] && [[ ! "$HUB_SUBNET_IDS" =~ \' ]]; then
    log "Fixing HUB_SUBNET_IDS format..."
    # Remove brackets, add quotes around each subnet, then add brackets back
    SUBNETS=$(echo "$HUB_SUBNET_IDS" | sed 's/\[//g' | sed 's/\]//g' | sed "s/subnet-/\\'subnet-/g" | sed "s/,/\\',/g")
    HUB_SUBNET_IDS="[${SUBNETS}']"
    export HUB_SUBNET_IDS
    log "Updated HUB_SUBNET_IDS: $HUB_SUBNET_IDS"
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
