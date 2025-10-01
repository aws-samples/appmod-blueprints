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

# Configuration
STUCK_SYNC_TIMEOUT=${STUCK_SYNC_TIMEOUT:-180}  # 3 minutes default for stuck sync operations

# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"
# Source environment variables first
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        if [ -f "$file" ]; then
            source "$file"
        fi
    done
fi

# Function to check and recover stuck applications
check_and_recover_stuck_apps() {
    local apps_to_check="$1"
    print_info "Checking for stuck applications..."
    
    # Get application status with operation state and start time
    local app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{" "}{.status.operationState.phase}{" "}{.status.operationState.startedAt}{"\n"}{end}' 2>/dev/null)
    
    local recovered=false
    
    # Check for stuck sync operations
    echo "$app_status" | while IFS=' ' read -r app health sync phase start_time; do
        if [ -n "$app" ] && [ "$phase" = "Running" ] && [ -n "$start_time" ]; then
            # Filter for specific apps if provided
            if [ -n "$apps_to_check" ] && ! echo "$apps_to_check" | grep -q "$app"; then
                continue
            fi
            
            local current_time=$(date -u +%s)
            local start_timestamp=$(date -d "$start_time" +%s 2>/dev/null || echo "0")
            local duration=$((current_time - start_timestamp))
            
            if [ $duration -gt $STUCK_SYNC_TIMEOUT ]; then
                print_warning "Found stuck sync for $app (running ${duration}s > ${STUCK_SYNC_TIMEOUT}s)"
                print_info "Terminating stuck operation for $app"
                argocd app terminate-op "$app" 2>/dev/null || true
                sleep 2
                
                print_info "Force syncing $app after termination"
                kubectl patch application "$app" -n argocd --type merge -p '{"operation":{"sync":{"syncStrategy":{"hook":{}}}}}' 2>/dev/null || true
                recovered=true
            fi
        fi
    done
    
    if [ "$recovered" = true ]; then
        print_info "Waiting 30 seconds for recovery operations to complete..."
        sleep 30
    fi
}

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

# Check for stuck applications first
check_and_recover_stuck_apps "kro-${RESOURCE_PREFIX}-hub-cluster kro-manifests-${RESOURCE_PREFIX}-hub-cluster"

for app in kro-${RESOURCE_PREFIX}-hub-cluster kro-manifests-${RESOURCE_PREFIX}-hub-cluster; do
  while [ "$(kubectl get application $app -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null)" != "Synced" ]; do
    print_info "Waiting for $app to sync..."
    sleep 10
    # Check for stuck operations periodically
    check_and_recover_stuck_apps "$app"
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
    
    # Restart KRO every attempt as it's required for proper functionality
    print_step "Restarting kro deployment to refresh API discovery..."
    kubectl rollout restart deployment -n kro-system kro
    kubectl rollout status deployment -n kro-system kro --timeout=60s
    
    print_info "Waiting 30 seconds for KRO to process..."
    sleep 30
  fi
done

# Don't fail if some RGDs aren't active - continue with warning
if [ $attempt -eq $max_attempts ]; then
  print_warning "Some ResourceGraphDefinitions may not be Active, but continuing..."
  print_info "Active RGDs: $active_rgds"
  print_info "Inactive RGDs: $inactive_rgds"
fi

print_success "Account bootstrapping completed successfully."
print_info "Next step: Run 3-create-spoke-clusters.sh to create the spoke EKS clusters."
