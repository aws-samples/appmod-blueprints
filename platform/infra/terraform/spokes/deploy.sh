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

# Usage function
usage() {
  echo "Usage: deploy.sh <environment> [--cluster-name-prefix <prefix>] [--deploy-db]"
  echo "Example: deploy.sh dev"
  echo "Example with database: deploy.sh dev --deploy-db"
  echo "Example with custom cluster name prefix: deploy.sh dev --cluster-name-prefix peeks-spoke-test --deploy-db"
  echo ""
  echo "Required environment variables:"
  echo "  TFSTATE_BUCKET_NAME - S3 bucket for Terraform state"
  echo "  TFSTATE_LOCK_TABLE - DynamoDB table for Terraform state locking"
  echo "  AWS_REGION - AWS region for resources (optional, defaults to us-east-1)"
  exit 1
}

# Wait for GitLab CloudFront distribution
wait_for_gitlab_distribution() {
  log "Waiting for GitLab CloudFront distribution to be created by hub cluster..."
  local gitlab_domain=""
  local max_attempts=30
  local attempt=0

  while [[ $attempt -lt $max_attempts ]]; do
    log "Attempt $((attempt + 1))/$max_attempts: Checking for GitLab CloudFront distribution..."
    
    gitlab_domain=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'gitlab')].DomainName | [0]" --output text 2>/dev/null || echo "None")
    
    if [[ "$gitlab_domain" != "None" && -n "$gitlab_domain" ]]; then
      log_success "Found GitLab CloudFront distribution: ${gitlab_domain}"
      echo "$gitlab_domain"
      return 0
    fi
    
    if [[ $attempt -eq $((max_attempts - 1)) ]]; then
      log "Warning: GitLab CloudFront distribution not found after $max_attempts attempts"
      log "Continuing with empty value..."
      echo ""
      return 0
    fi
    
    log "Waiting 30 seconds before next attempt..."
    sleep 30
    attempt=$((attempt + 1))
  done
}

# Deploy database
deploy_database() {
  local env=$1
  local cluster_name_prefix=$2
  
  log "Deploying database for $env environment..."
  
  if ! terraform -chdir=${SCRIPTDIR}/db init -reconfigure \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="key=spokes/db/${env}/terraform.tfstate" \
    -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}" \
    -backend-config="region=${AWS_REGION:-us-east-1}"; then
    log_error "Database terraform init failed"
    exit 1
  fi
  
  terraform -chdir=${SCRIPTDIR}/db workspace select -or-create $env
  
  if [ -n "$cluster_name_prefix" ]; then
    if ! terraform -chdir=${SCRIPTDIR}/db apply -var-file="../workspaces/${env}.tfvars" -var="cluster_name_prefix=$cluster_name_prefix" -auto-approve; then
      log_error "Database deployment failed with custom cluster name prefix"
      exit 1
    fi
  else
    if ! terraform -chdir=${SCRIPTDIR}/db apply -var-file="../workspaces/${env}.tfvars" -auto-approve; then
      log_error "Database deployment failed"
      exit 1
    fi
  fi
  
  log_success "Database deployment completed for $env"
}

# Deploy EKS cluster
deploy_eks_cluster() {
  local env=$1
  local cluster_name_prefix=$2
  local gitlab_domain=$3
  
  log "Deploying EKS cluster for $env environment..."

  if ! terraform -chdir=$SCRIPTDIR init --upgrade \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="key=spokes/${env}/terraform.tfstate" \
    -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}" \
    -backend-config="region=${AWS_REGION:-us-east-1}"; then
    log_error "Terraform init failed"
    exit 1
  fi

  terraform -chdir=$SCRIPTDIR workspace select -or-create $env

  # Apply with custom cluster name prefix if provided
  if [ -n "$cluster_name_prefix" ]; then
    log "Using custom cluster name prefix: $cluster_name_prefix"
    if ! terraform -chdir=$SCRIPTDIR apply \
      -var-file="workspaces/${env}.tfvars" \
      -var="cluster_name_prefix=$cluster_name_prefix" \
      -var="git_hostname=$gitlab_domain" \
      -var="gitlab_domain_name=$gitlab_domain" \
      -auto-approve; then
      log_error "EKS cluster deployment failed with custom cluster name prefix"
      exit 1
    fi
  else
    log "Using default cluster name prefix: peeks-spoke"
    if ! terraform -chdir=$SCRIPTDIR apply \
      -var-file="workspaces/${env}.tfvars" \
      -var="git_hostname=$gitlab_domain" \
      -var="gitlab_domain_name=$gitlab_domain" \
      -auto-approve; then
      log_error "EKS cluster deployment failed"
      exit 1
    fi
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
  local cluster_name_prefix=""
  local deploy_db=false

  while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
      --cluster-name-prefix)
        cluster_name_prefix="$2"
        shift
        shift
        ;;
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
  gitlab_domain=$(wait_for_gitlab_distribution)
  
  # Deploy database if requested
  if [ "$deploy_db" = true ]; then
    deploy_database "$env" "$cluster_name_prefix"
  fi
  
  # Deploy EKS cluster
  deploy_eks_cluster "$env" "$cluster_name_prefix" "$gitlab_domain"
  
  log_success "Spoke cluster deployment completed successfully for $env"
}

# Run main function
main "$@"
