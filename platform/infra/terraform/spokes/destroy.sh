#!/usr/bin/env bash

set -uo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

source "${ROOTDIR}/terraform/common.sh"

# Enhanced function to clean up ArgoCD applications in the correct order
cleanup_argocd_resources() {
  local env=$1
  echo "Starting enhanced ArgoCD cleanup for $env environment..."
  
  if ! kubectl get crd applications.argoproj.io &>/dev/null; then
    echo "ArgoCD CRDs not found, skipping cleanup"
    return 0
  fi

  # 1. First list all applications to understand what we're dealing with
  echo "Current ArgoCD applications:"
  kubectl get applications.argoproj.io -n argocd --no-headers 2>/dev/null || echo "No applications found"
  
  # 2. Delete workload applications first (non-addon applications)
  echo "Deleting workload applications first..."
  kubectl get applications.argoproj.io -n argocd -o json 2>/dev/null | \
    jq -r '.items[] | select(.metadata.name | test("cluster-addons|.*-addon") | not) | .metadata.name' | \
    while read -r app; do
      if [[ -n "$app" ]]; then
        echo "Removing finalizers from workload application: $app"
        kubectl patch applications.argoproj.io "$app" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
        echo "Deleting workload application: $app"
        kubectl delete applications.argoproj.io "$app" -n argocd --force --grace-period=0 --wait=false 2>/dev/null || true
      fi
    done
  
  # 3. Wait for workload applications to be deleted
  echo "Waiting for workload applications to be deleted..."
  sleep 15
  
  # 4. Delete LoadBalancer services before removing the controller
  echo "Cleaning up LoadBalancer services..."
  kubectl get services --all-namespaces --field-selector spec.type=LoadBalancer -o json 2>/dev/null | \
    jq -r '.items[]? | "\(.metadata.name) \(.metadata.namespace)"' | \
    while read -r name namespace; do
      if [ -n "$name" ] && [ -n "$namespace" ]; then
        echo "Deleting LoadBalancer: $name in $namespace"
        kubectl patch service "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
        kubectl delete service "$name" -n "$namespace" --force --grace-period=0 --wait=false 2>/dev/null || true
      fi
    done
  
  # 5. Scale down Karpenter nodes if available
  scale_down_karpenter_nodes
  
  # 6. Delete addon applications in specific order
  echo "Deleting addon applications in specific order..."
  
  # Define the order of addon deletion - leave critical addons for last
  ADDON_ORDER=(
    # Delete monitoring addons first
    "prometheus"
    "metrics-server"
    "cloudwatch-metrics"
    "aws-cloudwatch-metrics"
    
    # Delete non-critical addons
    "cert-manager"
    "external-dns"
    "external-secrets"
    "aws-efs-csi-driver"
    "aws-fsx-csi-driver"
    "aws-cloudwatch-observability"
    
    # Delete critical addons last
    "aws-ebs-csi-driver"
    "vpc-cni"
    "coredns"
    "aws-load-balancer-controller"
    "karpenter"
  )
  
  # Get all addon applications
  ADDON_APPS=$(kubectl get applications.argoproj.io -n argocd -o json 2>/dev/null | \
    jq -r '.items[] | select(.metadata.name | test("cluster-addons|.*-addon")) | .metadata.name')
  
  # First delete the addons in the specified order
  for addon in "${ADDON_ORDER[@]}"; do
    for app in $ADDON_APPS; do
      if [[ "$app" == *"$addon"* ]]; then
        echo "Removing finalizers from addon application: $app"
        kubectl patch applications.argoproj.io "$app" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
        echo "Deleting addon application: $app"
        kubectl delete applications.argoproj.io "$app" -n argocd --force --grace-period=0 --wait=false 2>/dev/null || true
        # Wait a bit for the deletion to process
        sleep 5
      fi
    done
  done
  
  # Delete any remaining addon applications not in the specific order
  echo "Deleting any remaining addon applications..."
  kubectl get applications.argoproj.io -n argocd -o json 2>/dev/null | \
    jq -r '.items[] | select(.metadata.name | test("cluster-addons|.*-addon")) | .metadata.name' | \
    while read -r app; do
      if [[ -n "$app" ]]; then
        echo "Removing finalizers from remaining addon application: $app"
        kubectl patch applications.argoproj.io "$app" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
        echo "Deleting remaining addon application: $app"
        kubectl delete applications.argoproj.io "$app" -n argocd --force --grace-period=0 --wait=false 2>/dev/null || true
      fi
    done
  
  # 7. Delete the cluster-addons ApplicationSet if it exists
  echo "Deleting cluster-addons ApplicationSet..."
  kubectl patch applicationsets.argoproj.io -n argocd cluster-addons --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
  kubectl delete applicationsets.argoproj.io -n argocd cluster-addons --force --grace-period=0 --wait=false 2>/dev/null || true
  
  # 8. Final check and cleanup of any remaining ArgoCD resources
  echo "Final cleanup of any remaining ArgoCD resources..."
  
  # Clean up any remaining applications
  kubectl get applications.argoproj.io -n argocd -o name 2>/dev/null | while read -r app; do
    if [[ -n "$app" ]]; then
      echo "Force removing finalizers from $app"
      kubectl patch "$app" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
      echo "Force deleting $app"
      kubectl delete "$app" -n argocd --force --grace-period=0 --wait=false 2>/dev/null || true
    fi
  done
  
  # Clean up any remaining applicationsets
  kubectl get applicationsets.argoproj.io -n argocd -o name 2>/dev/null | while read -r appset; do
    if [[ -n "$appset" ]]; then
      echo "Force removing finalizers from $appset"
      kubectl patch "$appset" -n argocd --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
      echo "Force deleting $appset"
      kubectl delete "$appset" -n argocd --force --grace-period=0 --wait=false 2>/dev/null || true
    fi
  done
  
  echo "ArgoCD cleanup completed for $env environment"
}

# Function to check if ArgoCD applications are stuck due to Git connectivity issues or Unknown status
check_argocd_git_connectivity() {
  local stuck_apps=()
  
  # Check each application for Git connectivity errors or Unknown status
  while IFS= read -r app_name; do
    if [[ -n "$app_name" ]]; then
      local error_msg=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.status.conditions[?(@.type=="ComparisonError")].message}' 2>/dev/null || echo "")
      local sync_status=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "")
      
      if [[ "$error_msg" == *"context deadline exceeded"* ]] || [[ "$error_msg" == *"timeout"* ]] || [[ "$error_msg" == *"connection refused"* ]] || [[ "$sync_status" == "Unknown" ]]; then
        stuck_apps+=("$app_name")
        echo "Found stuck application: $app_name (Status: $sync_status)"
        if [[ -n "$error_msg" ]]; then
          echo "Error: $error_msg"
        fi
      fi
    fi
  done < <(kubectl get applications.argoproj.io -n argocd -o jsonpath='{.items[*].metadata.name}' 2>/dev/null | tr ' ' '\n')
  
  if [[ ${#stuck_apps[@]} -gt 0 ]]; then
    echo "Found ${#stuck_apps[@]} applications stuck due to Git connectivity issues or Unknown status"
    return 0  # Found stuck apps
  else
    return 1  # No stuck apps found
  fi
}

# Function to check if any applications have Unknown status
check_unknown_status_apps() {
  local unknown_apps=()
  
  while IFS= read -r line; do
    if [[ -n "$line" ]]; then
      local app_name=$(echo "$line" | awk '{print $1}')
      local sync_status=$(echo "$line" | awk '{print $2}')
      
      if [[ "$sync_status" == "Unknown" ]]; then
        unknown_apps+=("$app_name")
      fi
    fi
  done < <(kubectl get applications.argoproj.io -n argocd --no-headers 2>/dev/null)
  
  if [[ ${#unknown_apps[@]} -gt 0 ]]; then
    echo "Found ${#unknown_apps[@]} applications with Unknown status: ${unknown_apps[*]}"
    return 0  # Found unknown apps
  else
    return 1  # No unknown apps found
  fi
}

if [[ $# -eq 0 ]] ; then
    echo "No arguments supplied"
    echo "Usage: destroy.sh <environment>"
    echo "Example: destroy.sh dev"
    exit 1
fi
env=$1
echo "Destroying $env ..."

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
terraform -chdir=$SCRIPTDIR workspace select -or-create $env

# Configure kubectl to access the cluster
TMPFILE=$(mktemp)
terraform -chdir=$SCRIPTDIR output -raw configure_kubectl > "$TMPFILE"
# check if TMPFILE contains the string "No outputs found"
if [[ ! $(cat $TMPFILE) == *"No outputs found"* ]]; then
  source "$TMPFILE"
fi

# Check if cluster is accessible and perform ArgoCD cleanup
if kubectl get nodes &>/dev/null; then
  echo "Cluster is accessible. Proceeding with ArgoCD cleanup..."
  
  # Check if ArgoCD CRDs exist
  if kubectl get crd applications.argoproj.io &>/dev/null; then
    echo "ArgoCD CRDs found. Starting cleanup process..."
    
    # Set a timeout to prevent infinite waiting (30 minutes max)
    TIMEOUT=1800  # 30 minutes in seconds
    ELAPSED=0
    SLEEP_INTERVAL=60
    GIT_CHECK_INTERVAL=180  # Check for Git connectivity issues every 3 minutes
    UNKNOWN_CHECK_INTERVAL=120  # Check for Unknown status every 2 minutes
    
    # Check for stuck applications immediately
    if check_argocd_git_connectivity || check_unknown_status_apps; then
      echo "Detected stuck applications. Initiating immediate cleanup..."
      cleanup_argocd_resources "$env"
    else
      # Wait for hub cluster to delete applications
      echo "Waiting for hub cluster to delete ArgoCD applications..."
      
      while [[ $(kubectl get applications.argoproj.io -n argocd 2>&1) != *"No resources found"* ]] && [[ $ELAPSED -lt $TIMEOUT ]]; do
        echo "Waiting for all argocd applications to be deleted by hub cluster: ${ELAPSED}s / ${TIMEOUT}s"
        
        # Show current Applications status
        echo "Current Applications:"
        kubectl get applications.argoproj.io -n argocd --no-headers 2>/dev/null | awk '{print "  - " $1 " (Status: " $2 ", Health: " $3 ")"}' || echo "  No applications found or error accessing them"
        
        # Check for Unknown status applications
        if [[ $((ELAPSED % UNKNOWN_CHECK_INTERVAL)) -eq 0 ]] && [[ $ELAPSED -gt 0 ]]; then
          if check_unknown_status_apps; then
            echo "Detected Applications with Unknown status. Initiating cleanup..."
            cleanup_argocd_resources "$env"
            break
          fi
        fi
        
        # Check for Git connectivity issues
        if [[ $((ELAPSED % GIT_CHECK_INTERVAL)) -eq 0 ]] && [[ $ELAPSED -gt 0 ]]; then
          if check_argocd_git_connectivity; then
            echo "Detected Git connectivity issues. Initiating cleanup..."
            cleanup_argocd_resources "$env"
            break
          fi
        fi
        
        sleep $SLEEP_INTERVAL
        ELAPSED=$((ELAPSED + SLEEP_INTERVAL))
        
        # If we've waited more than 5 minutes, check if all apps are in Unknown status
        if [[ $ELAPSED -ge 300 ]]; then
          all_unknown=true
          while IFS= read -r line; do
            if [[ -n "$line" ]]; then
              sync_status=$(echo "$line" | awk '{print $2}')
              if [[ "$sync_status" != "Unknown" ]]; then
                all_unknown=false
                break
              fi
            fi
          done < <(kubectl get applications.argoproj.io -n argocd --no-headers 2>/dev/null)
          
          if [[ "$all_unknown" == "true" ]]; then
            echo "All applications are in Unknown status. Initiating cleanup..."
            cleanup_argocd_resources "$env"
            break
          fi
        fi
      done
      
      # If timeout reached, force cleanup
      if [[ $ELAPSED -ge $TIMEOUT ]]; then
        echo "Timeout reached. Initiating force cleanup..."
        cleanup_argocd_resources "$env"
      fi
    fi
  else
    echo "ArgoCD CRDs not found. Skipping ArgoCD cleanup."
  fi
  
  # Delete all load balancers
  echo "Deleting all LoadBalancer services..."
  kubectl get services --all-namespaces -o custom-columns="NAME:.metadata.name,NAMESPACE:.metadata.namespace,TYPE:.spec.type" | \
  grep LoadBalancer | \
  while read -r name namespace type; do
    echo "Deleting service $name in namespace $namespace of type $type"
    kubectl delete --cascade='foreground' service "$name" -n "$namespace" --force --grace-period=0 || true
  done
fi

# Terraform destroy in proper order with better error handling
echo "Starting Terraform destroy process..."

# First destroy the gitops bridge bootstrap
echo "Destroying gitops_bridge_bootstrap_hub module..."
terraform -chdir=$SCRIPTDIR destroy -target="module.gitops_bridge_bootstrap_hub" -auto-approve -var-file="workspaces/${env}.tfvars" || true

# Then destroy the EKS addons
echo "Destroying eks_blueprints_addons module..."
terraform -chdir=$SCRIPTDIR destroy -target="module.eks_blueprints_addons" -auto-approve -var-file="workspaces/${env}.tfvars" || true

# Then destroy the EKS cluster
echo "Destroying eks module..."
terraform -chdir=$SCRIPTDIR destroy -target="module.eks" -auto-approve -var-file="workspaces/${env}.tfvars" || true

# Force delete VPC if requested
if [[ "${FORCE_DELETE_VPC:-false}" == "true" ]]; then
  echo "Force deleting VPC resources..."
  force_delete_vpc "peeks-spoke-${env}"
fi

# Destroy VPC
echo "Destroying vpc module..."
terraform -chdir=$SCRIPTDIR destroy -target="module.vpc" -auto-approve -var-file="workspaces/${env}.tfvars" || true

# Final destroy to clean up any remaining resources
echo "Running final terraform destroy..."
terraform -chdir=$SCRIPTDIR destroy -auto-approve -var-file="workspaces/${env}.tfvars"

echo "Destroy script completed for $env environment"