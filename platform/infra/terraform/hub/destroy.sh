#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

source "${ROOTDIR}/terraform/common.sh"

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

# Enhanced retry function with exponential backoff
retry_with_backoff() {
  local max_attempts=$1
  local delay=$2
  local command="${@:3}"
  local attempt=1
  
  while [ $attempt -le $max_attempts ]; do
    log "Attempt $attempt/$max_attempts: $command"
    
    if eval "$command"; then
      log_success "Command succeeded on attempt $attempt"
      return 0
    else
      if [ $attempt -eq $max_attempts ]; then
        log_error "Command failed after $max_attempts attempts"
        return 1
      fi
      
      log_warning "Command failed, waiting ${delay}s before retry..."
      sleep $delay
      delay=$((delay * 2))  # Exponential backoff
      attempt=$((attempt + 1))
    fi
  done
}

# Validate required environment variables and backend resources
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

# Initialize Terraform with S3 backend
initialize_terraform() {
  log "Initializing Terraform with S3 backend..."
  
  if ! terraform -chdir=$SCRIPTDIR init --upgrade \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}" \
    -backend-config="region=${AWS_REGION:-us-east-1}"; then
    log_error "Terraform initialization failed"
    exit 1
  fi
  
  log_success "Terraform initialized successfully"
}

# Check current AWS account and cluster status
preflight_checks() {
  log "Running pre-flight checks..."
  
  # Check AWS account
  CURRENT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
  if [ -z "$CURRENT_ACCOUNT" ]; then
    log_error "Cannot determine current AWS account. Check AWS credentials."
    exit 1
  fi
  log "Current AWS Account: $CURRENT_ACCOUNT"
  
  # Check if we can access terraform state
  if ! terraform -chdir=$SCRIPTDIR state list >/dev/null 2>&1; then
    log_warning "Cannot access Terraform state - may be empty"
    return 0
  fi
  
  # Check if cluster exists in state
  CLUSTER_NAME=$(terraform -chdir=$SCRIPTDIR output -raw cluster_name 2>/dev/null || echo "")
  if [ -n "$CLUSTER_NAME" ]; then
    log "Found cluster in state: $CLUSTER_NAME"
    
    # Check cluster status in AWS
    CLUSTER_STATUS=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.status' --output text 2>/dev/null || echo "NOT_FOUND")
    log "Cluster status in AWS: $CLUSTER_STATUS"
  else
    log_warning "No cluster found in Terraform state"
  fi
}

# Configure kubectl with fallback
configure_kubectl_with_fallback() {
  log "Configuring kubectl access..."
  
  # Try to configure kubectl if cluster exists
  if terraform -chdir=$SCRIPTDIR output -raw configure_kubectl 2>/dev/null | grep -v "No outputs found" > /dev/null; then
    if eval "$(terraform -chdir=$SCRIPTDIR output -raw configure_kubectl)"; then
      configure_eks_access
      log_success "kubectl configured successfully"
      
      # Test kubectl connection
      if kubectl get nodes --request-timeout=10s &>/dev/null; then
        log_success "kubectl can connect to cluster"
        return 0
      else
        log_warning "kubectl configured but cannot connect to cluster"
        return 1
      fi
    else
      log_warning "Failed to configure kubectl"
      return 1
    fi
  else
    log_warning "No kubectl configuration available"
    return 1
  fi
}

# Remove Kubernetes and Helm resources from Terraform state
remove_kubernetes_helm_resources_from_state() {
  log "Removing Kubernetes and Helm resources from Terraform state..."
  
  local k8s_helm_resources=(
    "kubernetes_namespace.argocd"
    "kubernetes_namespace.gitlab"
    "kubernetes_namespace.ingress_nginx"
    "kubernetes_secret.git_credentials"
    "kubernetes_secret.ide_password"
    "kubernetes_secret.git_secrets"
    "kubernetes_service.gitlab_nlb"
    "kubernetes_ingress_v1.argocd_nlb"
    "helm_release.ingress_nginx"
    "helm_release.argocd"
    "helm_release.gitlab"
  )
  
  for resource in "${k8s_helm_resources[@]}"; do
    if terraform -chdir=$SCRIPTDIR state show "$resource" &>/dev/null; then
      log "Removing $resource from state..."
      terraform -chdir=$SCRIPTDIR state rm "$resource" 2>/dev/null || true
    fi
  done
  
  # Remove any additional helm_release and kubernetes resources
  terraform -chdir=$SCRIPTDIR state list | grep -E "(helm_release|kubernetes_)" | while read -r resource; do
    if [ -n "$resource" ]; then
      log "Removing additional resource: $resource"
      terraform -chdir=$SCRIPTDIR state rm "$resource" 2>/dev/null || true
    fi
  done
  
  log_success "Kubernetes and Helm resources removed from state"
}

# Enhanced cleanup function for ArgoCD resources
cleanup_argocd_resources() {
  log "Starting ArgoCD cleanup..."
  
  if ! kubectl get ns argocd &>/dev/null; then
    log "ArgoCD namespace not found, skipping cleanup"
    return 0
  fi

  # Delete workload applications first
  local WORKLOAD_APPS=(peeks-members peeks-spoke-argocd peeks-members-init peeks-control-plane)
  
  for app in "${WORKLOAD_APPS[@]}"; do
    log "Deleting workload application: $app"
    kubectl patch applicationsets.argoproj.io -n argocd $app --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
    timeout 60s kubectl delete applicationsets.argoproj.io -n argocd $app --ignore-not-found=true --wait=false --force --grace-period=0 2>/dev/null || true
  done
  
  # Clean up remaining ArgoCD applications and ApplicationSets
  kubectl get applications.argoproj.io -n argocd -o name 2>/dev/null | while read -r app; do
    kubectl patch "$app" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
    kubectl delete "$app" -n argocd --ignore-not-found=true --wait=false --force --grace-period=0 2>/dev/null || true
  done
  
  kubectl get applicationsets.argoproj.io -n argocd -o name 2>/dev/null | while read -r appset; do
    kubectl patch "$appset" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
    kubectl delete "$appset" -n argocd --ignore-not-found=true --wait=false --force --grace-period=0 2>/dev/null || true
  done
  
  # Delete LoadBalancer services
  kubectl get services --all-namespaces --field-selector spec.type=LoadBalancer -o json 2>/dev/null | \
  jq -r '.items[]? | "\(.metadata.name) \(.metadata.namespace)"' | \
  while read -r name namespace; do
    if [ -n "$name" ] && [ -n "$namespace" ]; then
      log "Deleting LoadBalancer: $name in $namespace"
      kubectl patch service "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
      timeout 60s kubectl delete service "$name" -n "$namespace" --ignore-not-found=true --wait=false --force --grace-period=0 || true
    fi
  done
  
  # Delete cluster-addons
  kubectl patch applicationsets.argoproj.io -n argocd cluster-addons --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
  timeout 60s kubectl delete applicationsets.argoproj.io -n argocd cluster-addons --ignore-not-found=true --wait=false --force --grace-period=0 2>/dev/null || true
  
  log_success "ArgoCD cleanup completed"
}

# Cleanup Kubernetes resources with fallback
cleanup_kubernetes_resources_with_fallback() {
  log "Attempting to clean up Kubernetes resources..."
  
  # Test if kubectl is working
  if ! kubectl get nodes --request-timeout=10s &>/dev/null; then
    log_warning "kubectl cannot connect to cluster, removing resources from state only"
    remove_kubernetes_helm_resources_from_state
    return 0
  fi
  
  log_success "kubectl is working, proceeding with resource cleanup"
  cleanup_argocd_resources
  remove_kubernetes_helm_resources_from_state
}

# Destroy Terraform resources
destroy_terraform_resources() {
  log "Starting Terraform resource destruction..."
  
  local TARGETS=("module.gitops_bridge_bootstrap" "module.eks_blueprints_addons" "module.eks")
  
  for target in "${TARGETS[@]}"; do
    log "Destroying $target..."
    
    if retry_with_backoff 3 30 "terraform -chdir=$SCRIPTDIR destroy -target=\"$target\" -auto-approve"; then
      log_success "Successfully destroyed $target"
    else
      log_error "Failed to destroy $target after all attempts"
      log_warning "Continuing with next target..."
    fi
  done
  
  # Force delete VPC if requested
  if [[ "${FORCE_DELETE_VPC:-false}" == "true" ]]; then
    log "Force deleting VPC..."
    force_delete_vpc "peeks-hub-cluster"
  fi
  
  # Destroy VPC
  log "Destroying VPC..."
  if retry_with_backoff 3 30 "terraform -chdir=$SCRIPTDIR destroy -target=\"module.vpc\" -auto-approve"; then
    log_success "Successfully destroyed VPC"
  else
    log_error "Failed to destroy VPC after all attempts"
    log_warning "Continuing with final destroy..."
  fi
  
  # Final destroy
  log "Running final terraform destroy..."
  if retry_with_backoff 3 30 "terraform -chdir=$SCRIPTDIR destroy -auto-approve"; then
    log_success "Successfully completed final destroy"
  else
    log_error "Failed final destroy after all attempts. Manual cleanup may be required."
    return 1
  fi
}

# Main function
main() {
  log "Starting enhanced destroy script..."
  
  # Validate backend configuration
  validate_backend_config
  
  # Initialize Terraform
  initialize_terraform
  
  # Pre-flight checks
  preflight_checks
  
  # Configure kubectl with fallback
  if ! configure_kubectl_with_fallback; then
    log_warning "kubectl configuration failed, but continuing with destroy"
  fi
  
  # Clean up Kubernetes resources with fallback
  if ! cleanup_kubernetes_resources_with_fallback; then
    log_warning "Kubernetes cleanup had issues, but continuing with Terraform destroy"
  fi
  
  # Destroy Terraform resources
  if ! destroy_terraform_resources; then
    log_error "Critical failure: Terraform destroy failed"
    exit 1
  fi
  
  log_success "Destroy script completed successfully"
}

# Run main function
main "$@"
