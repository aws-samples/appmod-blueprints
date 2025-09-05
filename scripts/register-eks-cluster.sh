#!/bin/bash

# Script to register additional EKS clusters with ArgoCD
# Usage: ./register-eks-cluster.sh <cluster-name> <environment> [tenant]

if [ $# -lt 2 ]; then
    echo "Usage: $0 <cluster-name> <environment> [tenant]"
    echo "Example: $0 my-dev-cluster dev tenant1"
    echo "Example: $0 my-prod-cluster prod tenant1"
    exit 1
fi

CLUSTER_NAME="$1"
ENVIRONMENT="$2"
TENANT="${3:-tenant1}"

echo "Registering EKS cluster: $CLUSTER_NAME"

# Get cluster info
CLUSTER_ENDPOINT=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.endpoint' --output text)
CLUSTER_CA=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.certificateAuthority.data' --output text)
VPC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.resourcesVpcConfig.vpcId' --output text)
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")

if [ -z "$CLUSTER_ENDPOINT" ] || [ "$CLUSTER_ENDPOINT" = "None" ]; then
    echo "❌ Error: Cluster $CLUSTER_NAME not found"
    exit 1
fi

echo "✅ Found cluster: $CLUSTER_ENDPOINT"
echo "✅ VPC ID: $VPC_ID"

# Check if ArgoCD hub management role has access to the cluster
ARGOCD_ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/argocd-hub-mgmt"
echo "🔍 Checking access entries for ArgoCD role..."

if ! aws eks list-access-entries --cluster-name "$CLUSTER_NAME" --query "accessEntries[?contains(@, '$ARGOCD_ROLE_ARN')]" --output text | grep -q "$ARGOCD_ROLE_ARN"; then
    echo "➕ Adding ArgoCD hub management role to cluster access entries..."
    
    # Create access entry
    aws eks create-access-entry \
      --cluster-name "$CLUSTER_NAME" \
      --principal-arn "$ARGOCD_ROLE_ARN" \
      --type STANDARD > /dev/null
    
    # Associate cluster admin policy
    aws eks associate-access-policy \
      --cluster-name "$CLUSTER_NAME" \
      --principal-arn "$ARGOCD_ROLE_ARN" \
      --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
      --access-scope type=cluster > /dev/null
    
    echo "✅ ArgoCD role access configured"
else
    echo "✅ ArgoCD role already has access"
fi

# Create ArgoCD service account in the target cluster for authentication
echo "🔧 Creating ArgoCD service account in target cluster..."
kubectl --kubeconfig <(aws eks update-kubeconfig --name "$CLUSTER_NAME" --dry-run) apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: argocd-manager
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-manager
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: argocd-manager
  namespace: kube-system
---
apiVersion: v1
kind: Secret
metadata:
  name: argocd-manager-token
  namespace: kube-system
  annotations:
    kubernetes.io/service-account.name: argocd-manager
type: kubernetes.io/service-account-token
EOF

# Get the service account token
echo "🔑 Getting service account token..."
TOKEN=$(kubectl --kubeconfig <(aws eks update-kubeconfig --name "$CLUSTER_NAME" --dry-run) get secret argocd-manager-token -n kube-system -o jsonpath='{.data.token}' | base64 -d)

# 1. Create ArgoCD cluster secret for connectivity
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: $CLUSTER_NAME
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    aws_cluster_name: $CLUSTER_NAME
    cluster_name: $CLUSTER_NAME
    environment: $ENVIRONMENT
    tenant: $TENANT
    fleet_member: $ENVIRONMENT
    # Enable addons you want (customize as needed)
    enable_cert_manager: "true"
    enable_external_secrets: "true"
    enable_ingress_nginx: "true"
    enable_metrics_server: "true"
    enable_kyverno: "true"
    enable_ack_ec2: "true"
    enable_ack_eks: "true"
    enable_ack_iam: "true"
  annotations:
    # Core cluster info
    aws_account_id: "$AWS_ACCOUNT_ID"
    aws_region: "$AWS_REGION"
    aws_cluster_name: $CLUSTER_NAME
    cluster_name: $CLUSTER_NAME
    environment: $ENVIRONMENT
    aws_vpc_id: "$VPC_ID"
    
    # Repository configuration
    addons_repo_url: https://d1vvjck0a1cre3.cloudfront.net/user1/platform-on-eks-workshop.git
    addons_repo_basepath: gitops/addons/
    addons_repo_path: bootstrap
    addons_repo_revision: main
    
    fleet_repo_url: https://d1vvjck0a1cre3.cloudfront.net/user1/platform-on-eks-workshop.git
    fleet_repo_basepath: gitops/fleet/
    fleet_repo_path: bootstrap
    fleet_repo_revision: main
    
    workload_repo_url: https://d1vvjck0a1cre3.cloudfront.net/user1/platform-on-eks-workshop.git
    workload_repo_basepath: gitops/workloads/
    workload_repo_path: ""
    workload_repo_revision: main
    
    # Domain configuration
    ingress_domain_name: dlu6mbvnpgi1g.cloudfront.net
    gitlab_domain_name: d1vvjck0a1cre3.cloudfront.net
    
    # ArgoCD configuration
    argocd_namespace: argocd
    create_argocd_namespace: "false"
    
    # External Secrets
    external_secrets_namespace: external-secrets
    external_secrets_service_account: external-secrets-sa
    
    # Git configuration
    git_username: user1
    working_repo: platform-on-eks-workshop
    
    # ACK configuration
    ack_ec2_namespace: ack-system
    ack_ec2_service_account: ack-ec2-controller
    ack_eks_namespace: ack-system
    ack_eks_service_account: ack-eks-controller
    ack_iam_namespace: ack-system
    ack_iam_service_account: ack-iam-controller
    use_ack: "true"
type: Opaque
data:
  name: $(echo -n "$CLUSTER_NAME" | base64 -w 0)
  server: $(echo -n "$CLUSTER_ENDPOINT" | base64 -w 0)
  config: $(echo -n "{\"bearerToken\":\"$TOKEN\",\"tlsClientConfig\":{\"insecure\":false,\"caData\":\"$CLUSTER_CA\"}}" | base64 -w 0)
EOF

echo "✅ ArgoCD cluster secret created for $CLUSTER_NAME"
echo ""
echo "🎯 The existing ApplicationSets will automatically:"
echo "   - Deploy addons to your cluster"
echo "   - Manage workloads"
echo "   - Handle cluster lifecycle"
echo ""
echo "📊 Check status:"
echo "   kubectl get applications -n argocd | grep $CLUSTER_NAME"
