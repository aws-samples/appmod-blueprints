#!/usr/bin/env bash

set -uo pipefail

[[ -n "${DEBUG:-}" ]] && set -x


scale_down_karpenter_nodes() {

  # Delete the nodeclaims
  echo "Deleting Karpeneter NodePools"
  kubectl delete nodepools.karpenter.sh --all
  # do a final check to make sure the nodes are gone, loop sleep 60 in between checks
  nodes=$(kubectl get nodes -l karpenter.sh/registered=true -o jsonpath='{.items[*].metadata.name}')
  while [[ ! -z $nodes ]]; do
    kubectl delete nodepools.karpenter.sh --all
    echo "Waiting for nodes to be deleted: $nodes"
    sleep 60
    nodes=$(kubectl get nodes -l karpenter.sh/registered=true -o jsonpath='{.items[*].metadata.name}')
  done

}

# Function to check and configure EKS access entries
configure_eks_access() {
  local cluster_name="${CLUSTER_NAME:-${RESOURCE_PREFIX:-peeks}-hub-cluster}"
  local region="${AWS_DEFAULT_REGION:-${AWS_REGION:-us-east-1}}"
  
  echo "Checking EKS cluster access configuration for cluster: $cluster_name"
  
  # Get current AWS identity
  local current_arn=$(aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null)
  if [[ -z "$current_arn" ]]; then
    echo "Warning: Unable to get current AWS identity. Skipping access entry configuration."
    return 1
  fi
  
  echo "Current AWS identity: $current_arn"
  
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
    echo "Warning: Current identity is not a role. Skipping access entry configuration."
    return 1
  fi
  
  echo "Principal ARN: $principal_arn"
  
  # Check if cluster exists
  if ! aws eks describe-cluster --name "$cluster_name" --region "$region" >/dev/null 2>&1; then
    echo "EKS cluster $cluster_name not found or not accessible. Skipping access entry configuration."
    return 1
  fi
  
  # Check if access entry already exists
  if aws eks describe-access-entry --cluster-name "$cluster_name" --region "$region" --principal-arn "$principal_arn" >/dev/null 2>&1; then
    echo "Access entry already exists for $principal_arn"
    return 0
  fi
  
  echo "Creating access entry for $principal_arn..."
  
  # Create access entry
  if aws eks create-access-entry \
    --cluster-name "$cluster_name" \
    --region "$region" \
    --principal-arn "$principal_arn" \
    --type STANDARD >/dev/null 2>&1; then
    echo "Successfully created access entry"
  else
    echo "Warning: Failed to create access entry. It may already exist or you may lack permissions."
  fi
  
  # Associate cluster admin policy
  echo "Associating cluster admin policy..."
  if aws eks associate-access-policy \
    --cluster-name "$cluster_name" \
    --region "$region" \
    --principal-arn "$principal_arn" \
    --policy-arn "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy" \
    --access-scope type=cluster >/dev/null 2>&1; then
    echo "Successfully associated cluster admin policy"
  else
    echo "Warning: Failed to associate cluster admin policy. It may already be associated or you may lack permissions."
  fi
  
  # Wait a moment for the access entry to propagate
  echo "Waiting for access entry to propagate..."
  sleep 5
}


# This is required for certain resources that are not managed by Terraform
force_delete_vpc() {
  VPC_NAME=$1
  VPCID=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=${VPC_NAME}" --query "Vpcs[*].VpcId" --output text)
  if [ -n "$VPCID" ]; then
      echo "VPC ID: $VPCID"
      echo "Cleaning VPC endpoints if exists..."

      # Use AWS_REGION if set, otherwise default to the region from AWS CLI configuration
      REGION=${AWS_REGION:-$(aws configure get region)}

      vpc_endpoint_names=(
          "com.amazonaws.$REGION.guardduty-data"
          "com.amazonaws.$REGION.ssm"
          "com.amazonaws.$REGION.ec2messages"
          "com.amazonaws.$REGION.ssmmessages"
          "com.amazonaws.$REGION.s3"
      )

      for endpoint_name in "${vpc_endpoint_names[@]}"; do
          endpoint_exists=$(aws ec2 describe-vpc-endpoints --filters "Name=service-name,Values=$endpoint_name" "Name=vpc-id,Values=$VPCID" --query "VpcEndpoints[*].VpcEndpointId" --output text 2>/dev/null)
          if [ -n "$endpoint_exists" ]; then
              echo "Deleting VPC endpoint $endpoint_exists..."
              aws ec2 delete-vpc-endpoints --vpc-endpoint-ids "$endpoint_exists"
          fi
      done

      # check if aws-delete-vpc is available if not install it with go install github.com/megaproaktiv/aws-delete-vpc
      if ! command -v aws-delete-vpc &> /dev/null; then
          echo "aws-delete-vpc could not be found, installing it..."
          go install github.com/isovalent/aws-delete-vpc@latest
      fi
      echo "Cleaning VPC $VPCID"
      aws-delete-vpc -vpc-id=$VPCID
  fi
}