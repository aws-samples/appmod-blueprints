#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

# Logging functions
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >&2
}

log_error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

log_success() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: $1" >&2
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

# Usage function
usage() {
  echo "Usage: deploy.sh <environment> [--deploy-db]"
  echo "Example: deploy.sh dev"
  echo "Example with database: deploy.sh dev --deploy-db"
  echo ""
  echo "Required environment variables:"
  echo "  TFSTATE_BUCKET_NAME - S3 bucket for Terraform state"
  echo "  TFSTATE_LOCK_TABLE - DynamoDB table for Terraform state locking"
  echo "  AWS_REGION - AWS region for resources (optional, defaults to us-east-1)"
  echo "  RESOURCE_PREFIX - Prefix for resource names (optional, defaults to peeks)"
  exit 1
}

# Wait for GitLab CloudFront distribution
wait_for_gitlab_distribution() {
  log "Waiting for GitLab CloudFront distribution to be created by hub cluster..."
  local gitlab_domain=""
  local max_attempts=60  # Increased to 30 minutes
  local attempt=0

  while [[ $attempt -lt $max_attempts ]]; do
    log "Attempt $((attempt + 1))/$max_attempts: Checking for GitLab CloudFront distribution..."
    
    # Capture domain separately from logging to avoid mixing output
    gitlab_domain=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'gitlab')].DomainName | [0]" --output text 2>/dev/null || echo "None")
    
    if [[ "$gitlab_domain" != "None" && -n "$gitlab_domain" ]]; then
      log_success "Found GitLab CloudFront distribution: ${gitlab_domain}"
      # Return only the domain name, no log output
      echo "$gitlab_domain"
      return 0
    fi
    
    log "Waiting 30 seconds before next attempt..."
    sleep 30
    attempt=$((attempt + 1))
  done
  
  # If we reach here, GitLab distribution was not found after all attempts
  log_error "GitLab CloudFront distribution not found after $max_attempts attempts (30 minutes)"
  log_error "This is required for spoke cluster deployment. Please check hub cluster deployment."
  return 1
}

# Deploy database
deploy_database() {
  local env=$1
  
  log "Deploying database for $env environment..."
  
  # Set prefixes from RESOURCE_PREFIX environment variable
  RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
  CLUSTER_NAME_PREFIX="${RESOURCE_PREFIX:-peeks}-spoke"
  
  if ! terraform -chdir=${SCRIPTDIR}/db init -reconfigure \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="key=spokes/db/${env}/terraform.tfstate" \
    -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}" \
    -backend-config="region=${AWS_REGION:-us-east-1}"; then
    log_error "Database terraform init failed"
    exit 1
  fi
  
  terraform -chdir=${SCRIPTDIR}/db workspace select -or-create $env
  
  if ! terraform -chdir=${SCRIPTDIR}/db apply -var-file="../workspaces/${env}.tfvars" -var="cluster_name_prefix=$CLUSTER_NAME_PREFIX" -var="resource_prefix=$RESOURCE_PREFIX" -parallelism=3 -auto-approve; then
    log_error "Database deployment failed"
    exit 1
  fi
  
  log_success "Database deployment completed for $env"
}

# Deploy EKS cluster
deploy_eks_cluster() {
  local env=$1
  local gitlab_domain=$2
  
  log "Deploying EKS cluster for $env environment..."

  # Set prefixes from RESOURCE_PREFIX environment variable
  RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
  CLUSTER_NAME_PREFIX="${RESOURCE_PREFIX:-peeks}-spoke"

  if ! terraform -chdir=$SCRIPTDIR init --upgrade \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="key=spokes/${env}/terraform.tfstate" \
    -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}" \
    -backend-config="region=${AWS_REGION:-us-east-1}"; then
    log_error "Terraform init failed"
    exit 1
  fi

  terraform -chdir=$SCRIPTDIR workspace select -or-create $env

  log "Using cluster name prefix: $CLUSTER_NAME_PREFIX"
  if ! terraform -chdir=$SCRIPTDIR apply \
    -var-file="workspaces/${env}.tfvars" \
    -var="cluster_name_prefix=$CLUSTER_NAME_PREFIX" \
    -var="resource_prefix=$RESOURCE_PREFIX" \
    -var="git_hostname=$gitlab_domain" \
    -parallelism=3 \
    -auto-approve; then
    log_error "EKS cluster deployment failed"
    exit 1
  fi
}

# Main function
main() {
  if [[ $# -eq 0 ]]; then
    usage
  fi

  local env=$1
  shift

  # Parse additional command line arguments
  local deploy_db=false

  while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
      --deploy-db)
        deploy_db=true
        shift
        ;;
      *)
        shift
        ;;
    esac
  done

  log "Starting spoke cluster deployment for environment: $env"
  
  # Validate backend configuration
  validate_backend_config
  
  # Wait for GitLab distribution
  local gitlab_domain
  if ! gitlab_domain=$(wait_for_gitlab_distribution); then
    log_error "Failed to find GitLab CloudFront distribution. Aborting spoke deployment."
    exit 1
  fi
  
  # Deploy database if requested
  if [ "$deploy_db" = true ]; then
    deploy_database "$env"
  fi
  
  # Deploy EKS cluster
  deploy_eks_cluster "$env" "$gitlab_domain"
  
  log_success "Spoke cluster deployment completed successfully for $env"
}

# Run main function
main "$@"
