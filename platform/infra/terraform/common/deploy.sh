#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

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

# Main deployment function
main() {
  log "Starting common stack deployment..."
  
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
  
  # Apply Terraform configuration
  log "Applying git resources..."
  if ! terraform -chdir=$SCRIPTDIR apply -auto-approve; then
    log_error "Terraform apply failed"
    exit 1
  fi
  
  # Wait for SSH access
  log "Waiting for SSH access to be configured..."
  sleep 10
  
  log_success "Common stack deployment completed successfully"
}

# Run main function
main "$@"
