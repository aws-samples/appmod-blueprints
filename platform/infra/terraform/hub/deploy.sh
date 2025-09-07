#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

source "${ROOTDIR}/terraform/common.sh"

TF_VAR_FILE=${TF_VAR_FILE:-"terraform.tfvars"}

# Logging functions
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

log_success() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: $1"
}

# Validate required environment variables
validate_backend_config() {
  log "Validating S3 backend configuration..."
  
  if [[ -z "${TFSTATE_BUCKET_NAME:-}" ]]; then
    log_error "TFSTATE_BUCKET_NAME environment variable is required"
    exit 1
  fi
  
  if [[ -z "${TFSTATE_LOCK_TABLE:-}" ]]; then
    log_error "TFSTATE_LOCK_TABLE environment variable is required"
    exit 1
  fi
  
  local region="${AWS_REGION:-us-east-1}"
  
  # Check if S3 bucket exists and is accessible
  if ! aws s3api head-bucket --bucket "${TFSTATE_BUCKET_NAME}" 2>/dev/null; then
    log_error "S3 bucket '${TFSTATE_BUCKET_NAME}' does not exist or is not accessible"
    exit 1
  fi
  
  # Check if DynamoDB table exists
  if ! aws dynamodb describe-table --table-name "${TFSTATE_LOCK_TABLE}" --region "${region}" >/dev/null 2>&1; then
    log_error "DynamoDB table '${TFSTATE_LOCK_TABLE}' does not exist or is not accessible in region '${region}'"
    exit 1
  fi
  
  log_success "Backend configuration validated"
  log "S3 Bucket: ${TFSTATE_BUCKET_NAME}"
  log "DynamoDB Table: ${TFSTATE_LOCK_TABLE}"
  log "Region: ${region}"
}

# Parse command line arguments
CLUSTER_NAME=""

while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    --cluster-name)
      CLUSTER_NAME="$2"
      shift
      shift
      ;;
    *)
      shift
      ;;
  esac
done

# Main deployment function
main() {
  log "Starting hub cluster deployment..."
  
  # Validate backend configuration
  validate_backend_config
  
  # Initialize Terraform with S3 backend
  log "Initializing Terraform with S3 backend..."
  if ! terraform -chdir=$SCRIPTDIR init --upgrade \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}" \
    -backend-config="region=${AWS_REGION:-us-east-1}"; then
    log_error "Terraform initialization failed"
    exit 1
  fi
  
  # Get AWS Account ID
  AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  log "Using AWS Account ID: $AWS_ACCOUNT_ID"
  
  # Apply with custom cluster name if provided
  if [ -n "$CLUSTER_NAME" ]; then
    log "Deploying with custom cluster name: $CLUSTER_NAME"
    if ! terraform -chdir=$SCRIPTDIR apply -var-file=$TF_VAR_FILE -var="cluster_name=$CLUSTER_NAME" -var="account_ids=$AWS_ACCOUNT_ID" -parallelism=5 -auto-approve; then
      log_error "Terraform apply failed for cluster $CLUSTER_NAME"
      exit 1
    fi
  else
    log "Deploying with default cluster name: peeks-hub-cluster"
    if ! terraform -chdir=$SCRIPTDIR apply -var-file=$TF_VAR_FILE -var="account_ids=$AWS_ACCOUNT_ID" -auto-approve; then
      log_error "Terraform apply failed for default cluster"
      exit 1
    fi
  fi
  
  log_success "Hub cluster deployment completed successfully"
}

# Run main function
main "$@"
