#!/usr/bin/env bash

# Disable Terraform color output to prevent ANSI escape sequences
export TF_CLI_ARGS="-no-color"

# set -euo pipefail  # Commented out to allow safe sourcing
GIT_ROOT_PATH=$(git rev-parse --show-toplevel)

[[ -n "${DEBUG:-}" ]] && set -x

source "${GIT_ROOT_PATH}/platform/infra/terraform/scripts/argocd-utils.sh"
source "${GIT_ROOT_PATH}/platform/infra/terraform/scripts/colors.sh"

export SKIP_GITLAB=${SKIP_GITLAB:-false}
export WS_PARTICIPANT_ROLE_ARN=${WS_PARTICIPANT_ROLE_ARN:-""}
export RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
export GIT_USERNAME=${GIT_USERNAME:-user1}
export USER1_PASSWORD=${USER1_PASSWORD:-${IDE_PASSWORD:-""}}
export CONFIG_FILE=${CONFIG_FILE:-"${GIT_ROOT_PATH}/platform/infra/terraform/hub-config.yaml"}
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-us-west-2}}"
export WORKSHOP_CLUSTERS=${WORKSHOP_CLUSTERS:-false}

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

# Update config file cluster regions if WORKSHOP_CLUSTERS
if [[ "$WORKSHOP_CLUSTERS" == "true" ]]; then
  log "Updating config file for workshop..."
  TEMP_CONFIG_FILE="$(mktemp).yaml"
  cp "$CONFIG_FILE" "$TEMP_CONFIG_FILE"

  yq eval '.clusters |= with_entries(.value.name = env(RESOURCE_PREFIX) + "-" + .value.name)' -i "$TEMP_CONFIG_FILE"
  yq eval '.clusters[].region = env(AWS_REGION)' -i "$TEMP_CONFIG_FILE"
  export CONFIG_FILE="$TEMP_CONFIG_FILE"
fi

export CLUSTER_NAMES=($(yq eval '.clusters[].name' "$CONFIG_FILE"))



# Function to update or add environment variable to ~/.bashrc.d/platform.sh
update_workshop_var() {
    local var_name="$1"
    local var_value="$2"
    local workshop_file="$HOME/.bashrc.d/platform.sh"
    
    # Check if variable already exists in the file
    if grep -q "^export ${var_name}=" "$workshop_file" 2>/dev/null; then
        # Variable exists, update it
        sed -i "s|^export ${var_name}=.*|export ${var_name}=\"${var_value}\"|" "$workshop_file"
        print_info "Updated ${var_name} in ${workshop_file}"
    else
        # Variable doesn't exist, add it
        echo "export ${var_name}=\"${var_value}\"" >> "$workshop_file"
        print_info "Added ${var_name} to ${workshop_file}"
    fi
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
   local cluster_name=$1
   local region="${AWS_REGION}"

   if ! aws eks update-kubeconfig --name "$cluster_name" \
      --region "${region}" \
      --alias "$cluster_name" &>/dev/null; then
     log_error "Kubeconfig can not be updated for cluster: $cluster_name"
     return 1
   fi
   
   if ! kubectl get nodes --request-timeout=10s &>/dev/null; then
      log_warning "kubectl can not connect to cluster: $cluster_name"
      if ! configure_eks_access "$cluster_name"; then
        log_error "Failed to configure EKS access for cluster: $cluster_name"
        return 1
      fi
   fi

  log_success "Kubeconfig updated successfully for cluster: $cluster_name"
  return 0
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

# Cleanup Kubernetes resources with fallback
cleanup_kubernetes_resources_with_fallback() {
  local env=$1
  log "Attempting to clean up Kubernetes resources for $env..."
  
  # Test if kubectl is working
  if ! kubectl get nodes --request-timeout=10s --context $env &>/dev/null; then
    log_warning "kubectl cannot connect to cluster, setting up kubectl access"
    configure_kubectl_with_fallback "$env" || {
      log_error "kubectl configuration failed, cannot proceed with cleanup"
      return 1
    }
  fi
  
  log_success "kubectl is working, proceeding with resource cleanup"

  # First round of AppSet deletion
  delete_argocd_appsets

  # Delete Bootstrap apps by patching finalizers
  delete_argocd_apps "${BOOTSTRAP_APPS[*]}" "delete" "true"

  # Second round of AppSet deletion if any created by BOOTSTRAP APPS
  delete_argocd_appsets

  # Delete all kyverno apps as it blocks resource deletion
  delete_argocd_apps "kyverno" "delete" "false"

  #TODO: Remove this once we have a better way to handle webhook deletion
  kubectl delete mutatingwebhookconfigurations.admissionregistration.k8s.io kyverno-resource-mutating-webhook-cfg || true
  kubectl delete mutatingwebhookconfigurations.admissionregistration.k8s.io kyverno-verify-mutating-webhook-cfg || true
  kubectl delete mutatingwebhookconfigurations.admissionregistration.k8s.io kyverno-policy-mutating-webhook-cfg || true
  kubectl delete mutatingwebhookconfigurations.admissionregistration.k8s.io kargo || true
  kubectl delete validatingwebhookconfigurations.admissionregistration.k8s.io kyverno-cleanup-validating-webhook-cfg || true
  kubectl delete validatingwebhookconfigurations.admissionregistration.k8s.io kyverno-exception-validating-webhook-cfg || true
  kubectl delete validatingwebhookconfigurations.admissionregistration.k8s.io kyverno-global-context-validating-webhook-cfg || true
  kubectl delete validatingwebhookconfigurations.admissionregistration.k8s.io kyverno-policy-validating-webhook-cfg || true
  kubectl delete validatingwebhookconfigurations.admissionregistration.k8s.io kyverno-resource-validating-webhook-cfg || true
  kubectl delete validatingwebhookconfigurations.admissionregistration.k8s.io kyverno-ttl-validating-webhook-cfg || true
  
  # Delete all apps except core apps
  delete_argocd_apps "${CORE_APPS[*]}" "ignore" "false"

  # Delete external-secrets specifically
  delete_argocd_apps "external-secrets" "delete" "false"

  # Delete only ArgoCD apps of Core Apps by patching finalizer
  delete_argocd_apps "${CORE_APPS[*]}" "delete" "true"

  # Delete ArgoCD namespace if it exists
  log "Deleting ArgoCD namespace..."
  if ! kubectl delete namespace argocd --timeout=60s 2>/dev/null; then
      log "ArgoCD namespace didn't delete gracefully, Force deleting..."
      kubectl delete namespace argocd --force --grace-period=0 2>/dev/null || true
  fi
}

gitlab_repository_setup(){
  log "Setting up GitLab repository..."
  # Wait for GitLab to be accessible (5 minute timeout)
  local timeout=300
  local elapsed=0
  while ! curl -sf "https://${GITLAB_DOMAIN}" > /dev/null 2>&1; do
    sleep 5
    elapsed=$((elapsed + 5))
    if [ $elapsed -ge $timeout ]; then
      log_error "GitLab not accessible after 5 minutes"
      exit 1
    fi
  done
  
  cd "$GIT_ROOT_PATH"
  
  git config --global credential.helper store
  git config --global user.name "$GIT_USERNAME"
  git config --global user.email "$GIT_USERNAME@workshop.local"
  
  if ! git remote get-url gitlab >/dev/null 2>&1; then
    git remote add gitlab "https://${GIT_USERNAME}:${USER1_PASSWORD}@${GITLAB_DOMAIN}/${GIT_USERNAME}/${WORKING_REPO}.git"
  fi
  
  if ! git diff --quiet || ! git diff --cached --quiet; then
    git add .
    git commit -m "Updated bootstrap values in Backstag template and Created spoke cluster secret files " || true
  else
    print_info "No changes to commit"
  fi

  if ! git pull --rebase gitlab main; then
    log_warning "Failed to pull with rebase from GitLab"
  fi
  
  if ! git push --set-upstream gitlab "${WORKSHOP_GIT_BRANCH}":main --force; then
    if ! git push gitlab "${WORKSHOP_GIT_BRANCH}":main --force; then 
      log_error "Failed to push repository to GitLab"
      exit 1
    fi
  fi

  cd -
}

update_backstage_defaults() {
  print_header "Updating Backstage Template Configuration"

  cd "$GIT_ROOT_PATH"

  # Define catalog-info.yaml path
  CATALOG_INFO_PATH="${GIT_ROOT_PATH}/platform/backstage/templates/catalog-info.yaml"

  print_info "Using the following values for catalog-info.yaml update:"
  echo "  Account ID: $AWS_ACCOUNT_ID"
  echo "  AWS Region: $AWS_REGION"
  echo "  GitLab Domain: $GITLAB_DOMAIN"
  echo "  Git Username: $GIT_USERNAME"

  print_step "Updating catalog-info.yaml with environment-specific values"

  yq -i '
    (select(.metadata.name == "system-info").spec.gitlab_hostname) = "'$GITLAB_DOMAIN'" |
    (select(.metadata.name == "system-info").spec.argocd_hostname) = "'$ARGOCD_DOMAIN'" |
    (select(.metadata.name == "system-info").spec.gituser) = "'$GIT_USERNAME'" |
    (select(.metadata.name == "system-info").spec.aws_region) = "'$AWS_REGION'" |
    (select(.metadata.name == "system-info").spec.aws_account_id) = "'$AWS_ACCOUNT_ID'"
  ' "$CATALOG_INFO_PATH"

  print_success "Updated catalog-info.yaml with environment values"

  # Stage the modified file
  print_step "Staging catalog-info.yaml"
  # git add "$CATALOG_INFO_PATH"
  git add . # Add all
  print_success "Staged catalog-info.yaml"

  print_success "Backstage template configuration updated!"

  print_info "Templates can now reference these values using:"
  echo "  ✓ Hostname: \${{ steps['fetchSystem'].output.entity.spec.hostname }}"
  echo "  ✓ Git User: \${{ steps['fetchSystem'].output.entity.spec.gituser }}"
  echo "  ✓ AWS Region: \${{ steps['fetchSystem'].output.entity.spec.aws_region }}"
  echo "  ✓ AWS Account ID: \${{ steps['fetchSystem'].output.entity.spec.aws_account_id }}"

  print_info "Other templates should use the fetchSystem step to retrieve configuration from catalog-info.yaml"

  cd -
}

delete_backstage_ecr_repo() {
    if aws ecr describe-repositories --repository-names ${RESOURCE_PREFIX}-backstage --region $AWS_REGION > /dev/null 2>&1; then
        print_info "Deleting Backstage ECR repository..."
        aws ecr delete-repository --repository-name ${RESOURCE_PREFIX}-backstage --region $AWS_REGION --force > /dev/null 2>&1
        print_success "Backstage ECR repository deleted"
    else
        print_info "Backstage ECR repository does not exist"
    fi
}

create_spoke_cluster_secret_values() {

  cd "$GIT_ROOT_PATH"
  while IFS= read -r cluster_name; do
    local dir_path="gitops/fleet/members/fleet-${cluster_name}"
    mkdir -p "$dir_path"
    
    cat > "${dir_path}/values.yaml" << EOF
externalSecret:
  enabled: true
  clusterName: ${cluster_name}
  secretStoreRefKind: ClusterSecretStore
  secretStoreRefName: aws-secrets-manager
  secretManagerSecretNamePrefix: ${RESOURCE_PREFIX}
  server: remote
EOF
  done < <(yq '.clusters[] | select(.environment != "control-plane") | .name' "$CONFIG_FILE")

  git add .

  cd -
}
