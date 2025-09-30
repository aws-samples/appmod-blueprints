
# #!/usr/bin/env bash

# # Get cluster names from environment variables or use defaults
# HUB_CLUSTER_NAME=${HUB_CLUSTER_NAME:-peeks-hub-cluster}
# SPOKE_CLUSTER_PREFIX=${SPOKE_CLUSTER_NAME_PREFIX:-peeks-spoke}
# SPOKE_DEV_CLUSTER="${SPOKE_CLUSTER_PREFIX}-dev"
# SPOKE_PROD_CLUSTER="${SPOKE_CLUSTER_PREFIX}-prod"

# echo "Using the following cluster names:"
# echo "- Hub cluster: $HUB_CLUSTER_NAME"
# echo "- Spoke dev cluster: $SPOKE_DEV_CLUSTER"
# echo "- Spoke prod cluster: $SPOKE_PROD_CLUSTER"

# # Function to check if a cluster context exists
# cluster_context_exists() {
#     local cluster_name=$1
#     kubectl config get-contexts -o name | grep -q "^${cluster_name}$"
# }

# # Function to update kubeconfig if context doesn't exist
# update_kubeconfig_if_needed() {
#     local cluster_name=$1
#     local alias_name=$2

#     if ! cluster_context_exists "$alias_name"; then
#         echo "Updating kubeconfig for $cluster_name"
#         aws eks --region $AWS_REGION update-kubeconfig --name "$cluster_name" --alias "$alias_name"
#     fi
# }

# update_kubeconfig_if_needed_with_role() {
#     local cluster_name=$1
#     local alias_name=$2
#     local user_alias=$3
#     local role_arn=$4

#     if ! cluster_context_exists "$alias_name"; then
#         echo "Updating kubeconfig for $alias_name"
#         aws eks --region $AWS_REGION update-kubeconfig --name "$cluster_name" --alias "$alias_name" --user-alias "$user_alias" --role-arn "$role_arn"
#     fi
# }

# # Setup kubectx for EKS clusters as Admin
# update_kubeconfig_if_needed "$SPOKE_PROD_CLUSTER" "${SPOKE_PROD_CLUSTER}"
# update_kubeconfig_if_needed "$SPOKE_DEV_CLUSTER" "${SPOKE_DEV_CLUSTER}"
# update_kubeconfig_if_needed "$HUB_CLUSTER_NAME" "$HUB_CLUSTER_NAME"