#!/usr/bin/env bash

set -uo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

source "${ROOTDIR}/terraform/common.sh"

# Enhanced logging functions
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

# Pre-flight checks
preflight_checks() {
  log "Running pre-flight checks..."
  
  # Check if we're in the right AWS account
  CURRENT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
  if [ -z "$CURRENT_ACCOUNT" ]; then
    log_error "Cannot determine current AWS account. Check AWS credentials."
    exit 1
  fi
  
  log "Current AWS Account: $CURRENT_ACCOUNT"
  
  # Check if Terraform is initialized
  if [ ! -d ".terraform" ]; then
    log "Terraform not initialized, running terraform init..."
    if [[ -n "${TFSTATE_BUCKET_NAME:-}" && -n "${TFSTATE_LOCK_TABLE:-}" ]]; then
      terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${TFSTATE_BUCKET_NAME}" -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}"
    else
      # Try to get backend config from SSM parameters
      BUCKET_NAME=$(aws ssm get-parameter --name tf-backend-bucket --query 'Parameter.Value' --output text 2>/dev/null || echo "")
      LOCK_TABLE=$(aws ssm get-parameter --name tf-backend-lock-table --query 'Parameter.Value' --output text 2>/dev/null || echo "")
      
      if [[ -n "$BUCKET_NAME" && -n "$LOCK_TABLE" ]]; then
        terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${BUCKET_NAME}" -backend-config="dynamodb_table=${LOCK_TABLE}"
      else
        terraform -chdir=$SCRIPTDIR init --upgrade
        echo "WARNING: Backend configuration not found in environment variables or SSM parameters."
        echo "WARNING: Terraform state will be stored locally and may be lost!"
      fi
    fi
  fi
  
  # Check if cluster exists
  CLUSTER_NAME=$(terraform -chdir=$SCRIPTDIR output -raw cluster_name 2>/dev/null || echo "")
  if [ -n "$CLUSTER_NAME" ]; then
    log "Found cluster: $CLUSTER_NAME"
    
    # Check cluster status
    CLUSTER_STATUS=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.status' --output text 2>/dev/null || echo "NOT_FOUND")
    log "Cluster status: $CLUSTER_STATUS"
  else
    log_warning "No cluster found in Terraform state"
  fi
}

# Backup Terraform state
backup_terraform_state() {
  if [ -f "terraform.tfstate" ]; then
    cp terraform.tfstate "terraform.tfstate.backup.$(date +%Y%m%d_%H%M%S)"
    log "Terraform state backed up"
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
    # Kubernetes resources
    "kubernetes_namespace.argocd"
    "kubernetes_namespace.gitlab"
    "kubernetes_namespace.ingress_nginx"
    "kubernetes_secret.git_credentials"
    "kubernetes_secret.ide_password"
    "kubernetes_secret.git_secrets"
    "kubernetes_service.gitlab_nlb"
    "kubernetes_ingress_v1.argocd_nlb"
    # Helm resources
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
  
  # Also remove any other helm_release resources that might exist
  log "Scanning for additional helm_release resources..."
  terraform -chdir=$SCRIPTDIR state list | grep "helm_release" | while read -r resource; do
    if [ -n "$resource" ]; then
      log "Removing additional helm resource: $resource"
      terraform -chdir=$SCRIPTDIR state rm "$resource" 2>/dev/null || true
    fi
  done
  
  # Remove any kubernetes resources that might exist
  log "Scanning for additional kubernetes resources..."
  terraform -chdir=$SCRIPTDIR state list | grep "kubernetes_" | while read -r resource; do
    if [ -n "$resource" ]; then
      log "Removing additional kubernetes resource: $resource"
      terraform -chdir=$SCRIPTDIR state rm "$resource" 2>/dev/null || true
    fi
  done
  
  log_success "Kubernetes and Helm resources removed from state"
}

# Test if Terraform Kubernetes and Helm providers can connect
test_kubernetes_helm_providers() {
  log "Testing Terraform Kubernetes and Helm provider connections..."
  
  local providers_working=true
  
  # Test Kubernetes provider
  if ! terraform -chdir=$SCRIPTDIR plan -target="kubernetes_namespace.argocd" &>/dev/null; then
    log_warning "Terraform Kubernetes provider cannot connect"
    providers_working=false
  fi
  
  # Test Helm provider
  if ! terraform -chdir=$SCRIPTDIR plan -target="helm_release.ingress_nginx" &>/dev/null; then
    log_warning "Terraform Helm provider cannot connect"
    providers_working=false
  fi
  
  if [ "$providers_working" = true ]; then
    log_success "Both Terraform Kubernetes and Helm providers are working"
    return 0
  else
    log_warning "One or more Terraform providers cannot connect to Kubernetes"
    return 1
  fi
}

# Enhanced cleanup function for ArgoCD resources
cleanup_argocd_resources() {
  log "Starting enhanced ArgoCD cleanup..."
  
  if ! kubectl get ns argocd &>/dev/null; then
    log "ArgoCD namespace not found, skipping cleanup"
    return 0
  fi

  # 1. Delete workload applications first (but keep cluster-addons for last)
  local WORKLOAD_APPS=(peeks-members peeks-spoke-argocd peeks-members-init peeks-control-plane)
  
  for app in "${WORKLOAD_APPS[@]}"; do
    log "Deleting workload application: $app"
    # Remove finalizers first
    kubectl patch applicationsets.argoproj.io -n argocd $app --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
    # Force delete with longer timeout
    timeout 60s kubectl delete applicationsets.argoproj.io -n argocd $app --ignore-not-found=true --wait=false --force --grace-period=0 2>/dev/null || true
  done
  
  # 2. Clean up any remaining ArgoCD applications
  log "Cleaning up remaining ArgoCD applications..."
  kubectl get applications.argoproj.io -n argocd -o name 2>/dev/null | while read -r app; do
    log "Removing finalizers from $app"
    kubectl patch "$app" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
    kubectl delete "$app" -n argocd --ignore-not-found=true --wait=false --force --grace-period=0 2>/dev/null || true
  done
  
  # 3. Clean up any remaining ApplicationSets
  log "Cleaning up remaining ApplicationSets..."
  kubectl get applicationsets.argoproj.io -n argocd -o name 2>/dev/null | while read -r appset; do
    log "Removing finalizers from $appset"
    kubectl patch "$appset" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
    kubectl delete "$appset" -n argocd --ignore-not-found=true --wait=false --force --grace-period=0 2>/dev/null || true
  done
  
  # 4. Wait for workloads to terminate
  log "Waiting for workloads to terminate..."
  sleep 15
  
  # 5. Delete LoadBalancer services before removing the controller
  log "Cleaning up LoadBalancer services..."
  kubectl get services --all-namespaces --field-selector spec.type=LoadBalancer -o json 2>/dev/null | \
  jq -r '.items[]? | "\(.metadata.name) \(.metadata.namespace)"' | \
  while read -r name namespace; do
    if [ -n "$name" ] && [ -n "$namespace" ]; then
      log "Deleting LoadBalancer: $name in $namespace"
      kubectl patch service "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
      timeout 60s kubectl delete service "$name" -n "$namespace" --ignore-not-found=true --wait=false --force --grace-period=0 || true
    fi
  done
  
  # 6. Delete cluster-addons (controllers like load-balancer-controller)
  log "Deleting cluster-addons (controllers)..."
  kubectl patch applicationsets.argoproj.io -n argocd cluster-addons --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
  timeout 60s kubectl delete applicationsets.argoproj.io -n argocd cluster-addons --ignore-not-found=true --wait=false --force --grace-period=0 2>/dev/null || true
  
  # 7. Force cleanup of ArgoCD namespace if it's stuck
  log "Checking ArgoCD namespace status..."
  if kubectl get ns argocd -o jsonpath='{.status.phase}' 2>/dev/null | grep -q "Terminating"; then
    log "ArgoCD namespace is stuck in Terminating state, attempting force cleanup..."
    
    # Remove finalizers from the namespace
    kubectl patch namespace argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
    
    # Try to delete any remaining resources in the namespace
    kubectl delete all --all -n argocd --force --grace-period=0 2>/dev/null || true
    kubectl delete pvc --all -n argocd --force --grace-period=0 2>/dev/null || true
    kubectl delete secrets --all -n argocd --force --grace-period=0 2>/dev/null || true
    kubectl delete configmaps --all -n argocd --force --grace-period=0 2>/dev/null || true
    
    # Final attempt to delete the namespace
    kubectl delete namespace argocd --force --grace-period=0 2>/dev/null || true
  fi
  
  log_success "ArgoCD cleanup completed"
}

# Enhanced cleanup function with fallback for Kubernetes and Helm provider issues
cleanup_kubernetes_resources_with_fallback() {
  log "Attempting to clean up Kubernetes resources..."
  
  # Test if kubectl is working
  if ! kubectl get nodes --request-timeout=10s &>/dev/null; then
    log_warning "kubectl cannot connect to cluster, skipping Kubernetes cleanup"
    log "Kubernetes resources will be cleaned up when cluster is destroyed"
    remove_kubernetes_helm_resources_from_state
    return 0
  fi
  
  # Test if Terraform can connect to Kubernetes and Helm providers
  if ! test_kubernetes_helm_providers; then
    log_warning "Terraform Kubernetes/Helm providers cannot connect"
    remove_kubernetes_helm_resources_from_state
    log "Kubernetes and Helm resources removed from state, will be cleaned up with cluster"
    return 0
  fi
  
  # If we get here, both kubectl and Terraform providers are working
  log_success "kubectl and Terraform Kubernetes/Helm providers are working"
  cleanup_argocd_resources
}

# Destroy Terraform resources with improved error handling
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
  
  # Destroy VPC with retries
  log "Destroying VPC..."
  if retry_with_backoff 3 30 "terraform -chdir=$SCRIPTDIR destroy -target=\"module.vpc\" -auto-approve"; then
    log_success "Successfully destroyed VPC"
  else
    log_error "Failed to destroy VPC after all attempts"
    log_warning "Continuing with final destroy..."
  fi
  
  # Final destroy with retries
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
  
  # Pre-flight checks
  preflight_checks
  
  # Backup state
  backup_terraform_state
  
  # Initialize Terraform
  if [[ -n "${TFSTATE_BUCKET_NAME:-}" && -n "${TFSTATE_LOCK_TABLE:-}" ]]; then
    terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${TFSTATE_BUCKET_NAME}" -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}"
  else
    # Try to get backend config from SSM parameters
    BUCKET_NAME=$(aws ssm get-parameter --name tf-backend-bucket --query 'Parameter.Value' --output text 2>/dev/null || echo "")
    LOCK_TABLE=$(aws ssm get-parameter --name tf-backend-lock-table --query 'Parameter.Value' --output text 2>/dev/null || echo "")
    
    if [[ -n "$BUCKET_NAME" && -n "$LOCK_TABLE" ]]; then
      terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${BUCKET_NAME}" -backend-config="dynamodb_table=${LOCK_TABLE}"
    else
      terraform -chdir=$SCRIPTDIR init --upgrade
      echo "WARNING: Backend configuration not found in environment variables or SSM parameters."
      echo "WARNING: Terraform state will be stored locally and may be lost!"
    fi
  fi
  
  # Configure kubectl with fallback
  configure_kubectl_with_fallback
  
  # Clean up Kubernetes resources with fallback
  cleanup_kubernetes_resources_with_fallback
  
  # Destroy Terraform resources
  if destroy_terraform_resources; then
    log_success "Destroy script completed successfully"
    return 0
  else
    log_error "Destroy script completed with errors"
    return 1
  fi
}

# Run main function
main "$@"
