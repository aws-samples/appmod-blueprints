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

  # Check for and clear any stale locks
  cd "$DEPLOY_SCRIPTDIR"
  if terraform state list &>/dev/null; then
    log "State accessible, no lock issues"
  else
    log_warning "State lock detected, attempting to force unlock"
    LOCK_ID=$(terraform force-unlock -force 2>&1 | grep -oP 'Lock ID: \K[a-f0-9-]+' || echo "")
    if [[ -n "$LOCK_ID" ]]; then
      log "Force unlocking with ID: $LOCK_ID"
      terraform force-unlock -force "$LOCK_ID" || log_warning "Force unlock failed, continuing anyway"
    fi
  fi
  cd -

  # Drain nodes before terraform destroy. Terraform deletes VPC routes concurrently
  # with EKS cluster deletion, which can strand nodes without network connectivity.
  # Disabling built-in nodepools ensures nodes are terminated before VPC teardown.
  log "Disabling built-in nodepools and draining nodes from all clusters..."
  for cluster_name in "${CLUSTER_NAMES[@]}"; do
    log "Disabling built-in nodepools for cluster: $cluster_name"
    aws eks update-cluster-config \
      --name "$cluster_name" \
      --region "${AWS_REGION}" \
      --compute-config '{"enabled":true,"nodePools":[]}' 2>&1 || log_warning "Failed to disable nodepools for $cluster_name"
    log "Waiting for cluster update to complete: $cluster_name"
    aws eks wait cluster-active --name "$cluster_name" --region "${AWS_REGION}" 2>&1 || log_warning "Wait timed out for $cluster_name"

    # Delete any remaining nodepools (custom/GitOps-managed) via kubectl.
    if configure_kubectl_with_fallback "$cluster_name"; then
      log "Deleting any remaining nodepools from cluster: $cluster_name"
      kubectl delete nodepool --all \
        --context "$cluster_name" \
        --wait=true \
        --timeout=300s 2>&1 || log_warning "Failed to delete nodepools from $cluster_name (may already be empty)"
      log_success "Node drain complete for cluster: $cluster_name"
    else
      log_warning "Could not configure kubectl for $cluster_name, skipping remaining nodepool cleanup"
    fi
  done
  log "Pre-destroy node drain complete"

  # Destroy Terraform resources
  log "Destroying clusters stack..."
  if ! terraform -chdir=$DEPLOY_SCRIPTDIR destroy \
    -var-file="${GENERATED_TFVAR_FILE}" \
    -var="hub_vpc_id=${HUB_VPC_ID}" \
    -var="hub_subnet_ids=$(echo "${HUB_SUBNET_IDS}" | sed "s/'/\"/g")" \
    -var="resource_prefix=${RESOURCE_PREFIX}" \
    -var="workshop_participant_role_arn=${WS_PARTICIPANT_ROLE_ARN}" \
    -auto-approve; then
    log_warning "Clusters stack destroy failed, checking for lock issues"
    # Extract lock ID from error if present
    cd "$DEPLOY_SCRIPTDIR"
    LOCK_ID=$(terraform plan 2>&1 | grep -oP 'ID:\s+\K[a-f0-9-]+' | head -1 || echo "")
    if [[ -n "$LOCK_ID" ]]; then
      log "Forcing unlock with ID: $LOCK_ID"
      terraform force-unlock -force "$LOCK_ID" || true
    fi
    cd -
    log_warning "Retrying destroy after lock handling"
    if ! terraform -chdir=$DEPLOY_SCRIPTDIR destroy \
      -var-file="${GENERATED_TFVAR_FILE}" \
      -var="hub_vpc_id=${HUB_VPC_ID}" \
      -var="hub_subnet_ids=$(echo "${HUB_SUBNET_IDS}" | sed "s/'/\"/g")" \
      -var="resource_prefix=${RESOURCE_PREFIX}" \
      -var="workshop_participant_role_arn=${WS_PARTICIPANT_ROLE_ARN}" \
      -auto-approve; then
      log_error "Clusters stack destroy failed again, exiting"
      exit 1
    fi
  fi

  log_success "Clusters stack destroy completed successfully"
}

# Run main function
main "$@"
