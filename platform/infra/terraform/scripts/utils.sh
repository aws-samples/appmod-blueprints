#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

# set -euo pipefail  # Commented out to allow safe sourcing

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

source "${SCRIPTDIR}/argocd-utils.sh"

export SKIP_GITLAB=${SKIP_GITLAB:-false}
export IS_WS=${IS_WS:-false}
export WS_PARTICIPANT_ROLE_ARN={$WS_PARTICIPANT_ROLE_ARN:-""}
export RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
export GIT_USERNAME=${GIT_USERNAME:-user1}
export CONFIG_FILE=${CONFIG_FILE:- "../hub-config.yaml"}
export AWS_REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-us-east-1}}"
CLUSTER_NAMES=($(yq eval '.clusters[].name' "$CONFIG_FILE"))

# Logging functions
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

log_warning() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1" >&2
}

log_success() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: $1"
}

# Function to check and configure EKS access entries
configure_eks_access() {
  local cluster_name=$1
  local region="${AWS_REGION}"
  
  log "Checking EKS cluster access configuration for cluster: $cluster_name"
  
  # Get current AWS identity
  local current_arn=$(aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null)
  if [[ -z "$current_arn" ]]; then
    log_warning "Unable to get current AWS identity. Skipping access entry configuration."
    return 1
  fi
  
  log "Current AWS identity: $current_arn"
  
  # Extract role ARN if it's an assumed role
  local principal_arn
  if [[ "$current_arn" == *":assumed-role/"* ]]; then
    # Convert assumed-role ARN to role ARN
    # From: arn:aws:sts::123456789012:assumed-role/RoleName/session-name
    # To: arn:aws:iam::123456789012:role/RoleName
    local account_id=$(echo "$current_arn" | cut -d':' -f5)
    local role_name=$(echo "$current_arn" | cut -d'/' -f2)
    principal_arn="arn:aws:iam::${account_id}:role/${role_name}"
  elif [[ "$current_arn" == *":role/"* ]]; then
    principal_arn="$current_arn"
  else
    log_warning "Current identity is not a role. Skipping access entry configuration."
    return 1
  fi
  
  log "Principal ARN: $principal_arn"
  
  # Check if cluster exists
  if ! aws eks describe-cluster --name "$cluster_name" --region "$region" >/dev/null 2>&1; then
    log_warning "EKS cluster $cluster_name not found or not accessible. Skipping access entry configuration."
    return 1
  fi
  
  # Check if access entry already exists
  if aws eks describe-access-entry --cluster-name "$cluster_name" --region "$region" --principal-arn "$principal_arn" >/dev/null 2>&1; then
    log "Access entry already exists for $principal_arn"
    return 0
  fi
  
  log "Creating access entry for $principal_arn..."
  
  # Create access entry
  if aws eks create-access-entry \
    --cluster-name "$cluster_name" \
    --region "$region" \
    --principal-arn "$principal_arn" \
    --type STANDARD >/dev/null 2>&1; then
    log_success "Successfully created access entry"
  else
    log_warning "Failed to create access entry. It may already exist or you may lack permissions."
  fi
  
  # Associate cluster admin policy
  log "Associating cluster admin policy..."
  if aws eks associate-access-policy \
    --cluster-name "$cluster_name" \
    --region "$region" \
    --principal-arn "$principal_arn" \
    --policy-arn "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy" \
    --access-scope type=cluster >/dev/null 2>&1; then
    log_success "Successfully associated cluster admin policy"
  else
    log_warning "Failed to associate cluster admin policy. It may already be associated or you may lack permissions."
  fi
  
  # Wait a moment for the access entry to propagate
  log "Waiting for access entry to propagate..."
  sleep 5
}

# Configure kubectl with fallback
configure_kubectl_with_fallback() {
  log "Configuring kubectl access..."
   local cluster_name="${TF_VAR_resource_prefix}-$1"
   local region="${AWS_REGION}"

   if ! aws eks update-kubeconfig --name "$cluster_name" \
      --region "${region}" \
      --alias "$cluster_name" &>/dev/null; then
     log_warning "kubectl can not be configured for cluster: $cluster_name"
     configure_eks_access "$cluster_name"
   fi

   
   if kubectl get nodes --request-timeout=10s &>/dev/null; then
      log_success "kubectl can connect to cluster: $cluster_name"
      return 0
   fi

  log_error "kubectl configuration failed for cluster: $cluster_name "
  return 1  
}

# Validate required environment variables and backend resources
validate_backend_config() {
  log "Validating S3 backend configuration..."
  
  if [[ -z "${TFSTATE_BUCKET_NAME:-}" ]]; then
    log_error "TFSTATE_BUCKET_NAME environment variable is required"
    exit 1
  fi
  
  # Check if S3 bucket exists and is accessible
  if ! aws s3api head-bucket --bucket "${TFSTATE_BUCKET_NAME}" 2>/dev/null; then
    log_error "S3 bucket '${TFSTATE_BUCKET_NAME}' does not exist or is not accessible"
    exit 1
  fi
  
  log_success "Backend configuration validated"
  log "S3 Bucket: ${TFSTATE_BUCKET_NAME}"
}

# Initialize Terraform with S3 backend
initialize_terraform() {
  local module_name=$1
  local script_dir=$2

  log "Initializing Terraform with S3 backend for $module_name..."
  
  if ! terraform -chdir=$script_dir init --upgrade \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="region=${AWS_REGION}"; then
    log_error "Terraform initialization failed"
    exit 1
  fi
  
  log_success "Terraform initialized successfully"
}

# Check current AWS account and cluster status
check_cluster_status() {
  local cluster_name="${TF_VAR_resource_prefix}-$1"
  log "Checking $cluster_name cluster status..."
  # Check AWS account
  CURRENT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
  if [ -z "$CURRENT_ACCOUNT" ]; then
    log_error "Cannot determine current AWS account. Check AWS credentials."
    exit 1
  fi
  log "Current AWS Account: $CURRENT_ACCOUNT"

  CLUSTER_STATUS=$(aws eks describe-cluster --name "$cluster_name" --query 'cluster.status' --output text 2>/dev/null || echo "NOT_FOUND")

  if [ "$CLUSTER_STATUS" == "NOT_FOUND" ]; then
    log_error "Cluster $cluster_name not found in AWS"
    exit 1
  fi

  log "Cluster status in AWS: $CLUSTER_STATUS"
}

# Cleanup Kubernetes resources with fallback
cleanup_kubernetes_resources_with_fallback() {
  local env=$1
  log "Attempting to clean up Kubernetes resources for $env..."
  
  # Test if kubectl is working
  if ! kubectl get nodes --request-timeout=10s &>/dev/null; then
    log_warning "kubectl cannot connect to cluster, setting up kubectl access"
    configure_kubectl_with_fallback "$env" || {
      log_error "kubectl configuration failed, cannot proceed with cleanup"
      return 1
    }
  fi
  
  log_success "kubectl is working, proceeding with resource cleanup"

  delete_argocd_appsets

  delete_argocd_apps "${CORE_APPS[*]}" # will ignore core apps for cleanup

  delete_argocd_apps "${CORE_APPS[*]}" "only" # will not ignore core apps for final cleanup
}
