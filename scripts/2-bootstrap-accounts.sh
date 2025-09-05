#!/bin/bash

#############################################################################
# Bootstrap Management and Spoke Accounts
#############################################################################
#
# DESCRIPTION:
#   This script bootstraps the management and spoke AWS accounts for EKS
#   cluster management. It:
#   1. Creates ACK workload roles with the current user added
#   2. Monitors ResourceGraphDefinitions until they are all in Active state
#   3. Restarts the KRO deployment if needed to activate resources
#
# USAGE:
#   ./2-bootstrap-accounts.sh
#
# PREREQUISITES:
#   - ArgoCD and GitLab must be set up (run 1-argocd-gitlab-setup.sh first)
#   - The create_ack_workload_roles.sh script must be available
#   - kubectl must be configured to access the hub cluster
#
# SEQUENCE:
#   This is the third script (2) in the setup sequence.
#   Run after 1-argocd-gitlab-setup.sh and before 3-create-spoke-clusters.sh
#
#############################################################################

set -e

# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

print_header "Bootstrapping Management and Spoke Accounts"

print_step "Creating ACK workload roles"
if [ -f "$SCRIPT_DIR/create_ack_workload_roles.sh" ]; then
    MGMT_ACCOUNT_ID="$MGMT_ACCOUNT_ID" "$SCRIPT_DIR/create_ack_workload_roles.sh"
    if [ $? -eq 0 ]; then
        print_success "ACK workload roles created successfully"
    else
        print_error "ACK workload roles creation failed"
        exit 1
    fi
else
    print_error "ACK workload roles script not found at $SCRIPT_DIR/create_ack_workload_roles.sh"
    exit 1
fi

print_header "Checking ResourceGraphDefinitions Status"

# Wait for metrics-server to be fully ready first
print_step "Ensuring metrics-server is ready..."
kubectl wait --for=condition=Available deployment/metrics-server -n kube-system --timeout=300s

# Verify metrics API is accessible
print_step "Verifying metrics API accessibility..."
max_retries=10
retry=0
while [ $retry -lt $max_retries ]; do
  if kubectl top nodes >/dev/null 2>&1; then
    print_success "Metrics API is accessible"
    break
  fi
  retry=$((retry + 1))
  print_info "Waiting for metrics API to be ready (attempt $retry/$max_retries)..."
  sleep 10
done

# Wait for KRO applications to be fully deployed
print_step "Ensuring KRO applications are fully synced..."
for app in kro-peeks-hub-cluster kro-eks-rgs-peeks-hub-cluster; do
  while [ "$(kubectl get application $app -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null)" != "Synced" ]; do
    print_info "Waiting for $app to sync..."
    sleep 10
  done
  print_success "$app is synced"
done

# Wait for KRO deployment to be ready
print_step "Waiting for KRO deployment to be ready..."
kubectl wait --for=condition=Available deployment/kro -n kro-system --timeout=300s

print_info "Waiting for ResourceGraphDefinitions to be created and become Active..."

max_attempts=10
attempt=0

while [ $attempt -lt $max_attempts ]; do
  attempt=$((attempt + 1))
  
  total_rgds=$(kubectl get resourcegraphdefinitions.kro.run --no-headers 2>/dev/null | wc -l)
  
  if [ "$total_rgds" -eq 0 ]; then
    print_warning "No ResourceGraphDefinitions found yet (attempt $attempt/$max_attempts)"
    sleep 20
    continue
  fi
  
  active_rgds=$(kubectl get resourcegraphdefinitions.kro.run -o jsonpath='{.items[?(@.status.state=="Active")].metadata.name}' 2>/dev/null || echo "")
  inactive_rgds=$(kubectl get resourcegraphdefinitions.kro.run -o jsonpath='{.items[?(@.status.state!="Active")].metadata.name}' 2>/dev/null || echo "")
  
  print_info "Found $total_rgds ResourceGraphDefinitions total (attempt $attempt/$max_attempts)"
  
  if [ -n "$active_rgds" ]; then
    print_success "Active ResourceGraphDefinitions: $active_rgds"
  fi
  
  if [ -z "$inactive_rgds" ]; then
    print_success "All $total_rgds ResourceGraphDefinitions are in Active state!"
    break
  else
    print_warning "ResourceGraphDefinitions not yet Active: $inactive_rgds"
    
    # Restart KRO every time to refresh API discovery
    print_step "Restarting kro deployment to refresh API discovery..."
    kubectl rollout restart deployment -n kro-system kro
    kubectl rollout status deployment -n kro-system kro --timeout=60s
    
    print_info "Waiting 30 seconds for KRO to process..."
    sleep 30
  fi
done

if [ $attempt -eq $max_attempts ]; then
  print_error "Timeout: ResourceGraphDefinitions did not become Active after $max_attempts attempts"
  exit 1
fi

print_success "Account bootstrapping completed successfully."
print_info "Next step: Run 3-create-spoke-clusters.sh to create the spoke EKS clusters."
