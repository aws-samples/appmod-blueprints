#!/usr/bin/env bash
# create-cross-account-roles.sh
#
# Run this script from the HUB account to set up cross-account access for a target account.
# It will:
#   1. Assume a role in the target account to create cluster-mgmt-* roles
#   2. Update the hub ACK capability role to allow assuming target account roles
#   3. Update the hub ArgoCD capability role with EKS permissions on target
#
# Usage:
#   export TARGET_ACCOUNT_ID=586794472760
#   export RESOURCE_PREFIX=peeks
#   export HUB_CLUSTER_NAME=peeks-hub
#   ./create-cross-account-roles.sh

set -euo pipefail

TARGET_ACCOUNT_ID="${TARGET_ACCOUNT_ID:?Set TARGET_ACCOUNT_ID}"
RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
HUB_CLUSTER_NAME="${HUB_CLUSTER_NAME:-${RESOURCE_PREFIX}-hub}"
HUB_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ACK_CAPABILITY_ROLE="${RESOURCE_PREFIX}-${HUB_CLUSTER_NAME}-ack-capability-role"
ARGOCD_CAPABILITY_ROLE="${RESOURCE_PREFIX}-${HUB_CLUSTER_NAME}-argocd-capability-role"

echo "Hub account: $HUB_ACCOUNT_ID"
echo "Target account: $TARGET_ACCOUNT_ID"
echo "Resource prefix: $RESOURCE_PREFIX"
echo ""

###############################################################################
# Step 1: Create cluster-mgmt-* roles in target account
###############################################################################
echo "=== Step 1: Creating cluster-mgmt roles in target account ==="

TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::${HUB_ACCOUNT_ID}:root"},
      "Action": ["sts:AssumeRole", "sts:TagSession"],
      "Condition": {
        "ArnLike": {
          "aws:PrincipalArn": [
            "arn:aws:iam::${HUB_ACCOUNT_ID}:role/${RESOURCE_PREFIX}-*-ack-capability-role",
            "arn:aws:iam::${HUB_ACCOUNT_ID}:role/${RESOURCE_PREFIX}-ack-*-controller-role-*"
          ]
        }
      }
    }
  ]
}
EOF
)

declare -A MANAGED_POLICIES
MANAGED_POLICIES[ec2]="arn:aws:iam::aws:policy/AmazonEC2FullAccess arn:aws:iam::aws:policy/AmazonVPCFullAccess"
MANAGED_POLICIES[eks]="arn:aws:iam::aws:policy/AmazonEKSClusterPolicy arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
MANAGED_POLICIES[iam]="arn:aws:iam::aws:policy/IAMFullAccess"
MANAGED_POLICIES[ecr]="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess"
MANAGED_POLICIES[s3]="arn:aws:iam::aws:policy/AmazonS3FullAccess"
MANAGED_POLICIES[dynamodb]="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"

declare -A INLINE_POLICIES
INLINE_POLICIES[ec2]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ec2:*","elasticloadbalancing:*"],"Resource":"*"}]}'
INLINE_POLICIES[eks]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["eks:*","iam:PassRole","iam:GetRole"],"Resource":"*"}]}'
INLINE_POLICIES[iam]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["iam:*"],"Resource":"*"}]}'
INLINE_POLICIES[ecr]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ecr:*"],"Resource":"*"}]}'
INLINE_POLICIES[s3]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:*"],"Resource":"*"}]}'
INLINE_POLICIES[dynamodb]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["dynamodb:*"],"Resource":"*"}]}'

# Assume a bootstrap role in target account (requires initial trust setup)
echo "Assuming role in target account..."
CREDS=$(aws sts assume-role --role-arn "arn:aws:iam::${TARGET_ACCOUNT_ID}:role/${RESOURCE_PREFIX}-cluster-mgmt-iam" --role-session-name setup 2>/dev/null || \
        aws sts assume-role --role-arn "arn:aws:iam::${TARGET_ACCOUNT_ID}:role/OrganizationAccountAccessRole" --role-session-name setup 2>/dev/null || \
        echo "")

if [ -z "$CREDS" ]; then
  echo "ERROR: Cannot assume a role in target account $TARGET_ACCOUNT_ID."
  echo "Either create a trust relationship first, or run this section directly from the target account."
  exit 1
fi

export AWS_ACCESS_KEY_ID=$(echo $CREDS | jq -r '.Credentials.AccessKeyId')
export AWS_SECRET_ACCESS_KEY=$(echo $CREDS | jq -r '.Credentials.SecretAccessKey')
export AWS_SESSION_TOKEN=$(echo $CREDS | jq -r '.Credentials.SessionToken')

for service in ec2 eks iam ecr s3 dynamodb; do
  ROLE_NAME="${RESOURCE_PREFIX}-cluster-mgmt-${service}"
  echo "  Creating: $ROLE_NAME"

  if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
    aws iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "$TRUST_POLICY"
  else
    aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST_POLICY" --no-cli-pager >/dev/null
  fi

  for policy_arn in ${MANAGED_POLICIES[$service]}; do
    aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$policy_arn"
  done
  aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "${service}-permissions" --policy-document "${INLINE_POLICIES[$service]}"
done
echo "  ✅ Target account roles created"

# Clear target account creds
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

###############################################################################
# Step 2: Update hub ACK capability role
###############################################################################
echo ""
echo "=== Step 2: Updating hub ACK capability role ($ACK_CAPABILITY_ROLE) ==="

# Get existing policy and merge target account
EXISTING=$(aws iam get-role-policy --role-name "$ACK_CAPABILITY_ROLE" --policy-name AssumeWorkloadRoles --query 'PolicyDocument.Statement[0].Resource' --output json 2>/dev/null || echo '[]')
NEW_ARN="arn:aws:iam::${TARGET_ACCOUNT_ID}:role/${RESOURCE_PREFIX}-cluster-mgmt-*"

if echo "$EXISTING" | grep -q "$TARGET_ACCOUNT_ID"; then
  echo "  Target account already in AssumeWorkloadRoles policy"
else
  RESOURCES=$(echo "$EXISTING" | jq --arg new "$NEW_ARN" '. + [$new]')
  aws iam put-role-policy --role-name "$ACK_CAPABILITY_ROLE" --policy-name AssumeWorkloadRoles --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Action\": [\"sts:AssumeRole\", \"sts:TagSession\"],
      \"Resource\": $RESOURCES
    }]
  }"
  echo "  ✅ Added target account to AssumeWorkloadRoles"
fi

# Add secretsmanager permissions
aws iam put-role-policy --role-name "$ACK_CAPABILITY_ROLE" --policy-name secretsmanager-cross-account --policy-document '{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["secretsmanager:CreateSecret","secretsmanager:DeleteSecret","secretsmanager:DescribeSecret","secretsmanager:GetSecretValue","secretsmanager:ListSecrets","secretsmanager:PutSecretValue","secretsmanager:UpdateSecret","secretsmanager:TagResource"],
    "Resource": "*"
  }]
}'
echo "  ✅ Added secretsmanager permissions"

###############################################################################
# Step 3: Update hub ArgoCD capability role
###############################################################################
echo ""
echo "=== Step 3: Updating hub ArgoCD capability role ($ARGOCD_CAPABILITY_ROLE) ==="

aws iam put-role-policy --role-name "$ARGOCD_CAPABILITY_ROLE" --policy-name "cross-account-eks-${TARGET_ACCOUNT_ID}" --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Effect\": \"Allow\",
      \"Action\": [\"sts:AssumeRole\", \"sts:TagSession\"],
      \"Resource\": \"arn:aws:iam::${TARGET_ACCOUNT_ID}:role/${RESOURCE_PREFIX}-*-argocd-role\"
    },
    {
      \"Effect\": \"Allow\",
      \"Action\": [\"eks:DescribeCluster\", \"eks:ListClusters\", \"eks:AccessKubernetesApi\", \"eks:DescribeAccessEntry\", \"eks:ListAccessEntries\"],
      \"Resource\": \"arn:aws:eks:*:${TARGET_ACCOUNT_ID}:cluster/${RESOURCE_PREFIX}-*\"
    }
  ]
}"
echo "  ✅ Added cross-account EKS permissions to ArgoCD capability role"

###############################################################################
echo ""
echo "✅ Cross-account setup complete for account ${TARGET_ACCOUNT_ID}!"
echo ""
echo "NOTE: After the cluster is created, you still need to create an access entry"
echo "on the target cluster for the ArgoCD capability role. The RGD handles this"
echo "automatically, but if needed manually:"
echo ""
echo "  aws eks create-access-entry --cluster-name <CLUSTER> --region <REGION> \\"
echo "    --principal-arn arn:aws:iam::${HUB_ACCOUNT_ID}:role/${ARGOCD_CAPABILITY_ROLE} \\"
echo "    --type STANDARD"
echo "  aws eks associate-access-policy --cluster-name <CLUSTER> --region <REGION> \\"
echo "    --principal-arn arn:aws:iam::${HUB_ACCOUNT_ID}:role/${ARGOCD_CAPABILITY_ROLE} \\"
echo "    --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \\"
echo "    --access-scope type=cluster"
