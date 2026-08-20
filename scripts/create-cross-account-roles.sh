#!/usr/bin/env bash
# create-cross-account-roles.sh
#
# Sets up cross-account access for KRO-provisioned EKS clusters.
#
# Two modes:
#   --target-only  Run from the TARGET account to create cluster-mgmt-* roles (first time only)
#   (no flag)      Run from the HUB account to configure hub capability roles + target roles
#
# Usage:
#   # First time - run from target account:
#   export HUB_ACCOUNT_ID=515966522948
#   export RESOURCE_PREFIX=peeks
#   ./create-cross-account-roles.sh --target-only
#
#   # Then - run from hub account:
#   export TARGET_ACCOUNT_ID=586794472760
#   export RESOURCE_PREFIX=peeks
#   export HUB_CLUSTER_NAME=peeks-hub
#   ./create-cross-account-roles.sh

set -euo pipefail

RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
TARGET_ONLY=false
[[ "${1:-}" == "--target-only" ]] && TARGET_ONLY=true

###############################################################################
# Target account role creation (shared logic)
###############################################################################
create_target_roles() {
  local HUB_ACCOUNT_ID="$1"
  echo "Creating cluster-mgmt roles (trusting hub account $HUB_ACCOUNT_ID)..."

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
  MANAGED_POLICIES[secretsmanager]="arn:aws:iam::aws:policy/SecretsManagerReadWrite"

  declare -A INLINE_POLICIES
  INLINE_POLICIES[ec2]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ec2:*","elasticloadbalancing:*"],"Resource":"*"}]}'
  INLINE_POLICIES[eks]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["eks:*","iam:PassRole","iam:GetRole"],"Resource":"*"}]}'
  INLINE_POLICIES[iam]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["iam:*"],"Resource":"*"}]}'
  INLINE_POLICIES[ecr]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ecr:*"],"Resource":"*"}]}'
  INLINE_POLICIES[s3]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:*"],"Resource":"*"}]}'
  INLINE_POLICIES[dynamodb]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["dynamodb:*"],"Resource":"*"}]}'
  INLINE_POLICIES[secretsmanager]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["secretsmanager:*"],"Resource":"*"}]}'

  for service in ec2 eks iam ecr s3 dynamodb secretsmanager; do
    ROLE_NAME="${RESOURCE_PREFIX}-cluster-mgmt-${service}"
    if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
      aws iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "$TRUST_POLICY"
    else
      aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST_POLICY" --no-cli-pager >/dev/null
    fi
    for policy_arn in ${MANAGED_POLICIES[$service]}; do
      aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$policy_arn"
    done
    aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "${service}-permissions" --policy-document "${INLINE_POLICIES[$service]}"
    echo "  ✅ $ROLE_NAME"
  done
}

###############################################################################
# Mode: --target-only (run from target account)
###############################################################################
if [ "$TARGET_ONLY" = true ]; then
  HUB_ACCOUNT_ID="${HUB_ACCOUNT_ID:?Set HUB_ACCOUNT_ID when using --target-only}"
  TARGET_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  echo "=== Running from TARGET account ($TARGET_ACCOUNT_ID) ==="
  create_target_roles "$HUB_ACCOUNT_ID"
  echo ""
  echo "✅ Done! Now run this script from the hub account (without --target-only)"
  echo "   to configure the hub capability roles."
  exit 0
fi

###############################################################################
# Mode: full (run from hub account)
###############################################################################
TARGET_ACCOUNT_ID="${TARGET_ACCOUNT_ID:?Set TARGET_ACCOUNT_ID}"
HUB_CLUSTER_NAME="${HUB_CLUSTER_NAME:-${RESOURCE_PREFIX}-hub}"
HUB_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ACK_CAPABILITY_ROLE="${RESOURCE_PREFIX}-${HUB_CLUSTER_NAME}-ack-capability-role"
ARGOCD_CAPABILITY_ROLE="${RESOURCE_PREFIX}-${HUB_CLUSTER_NAME}-argocd-capability-role"

echo "=== Running from HUB account ($HUB_ACCOUNT_ID) ==="
echo "Target: $TARGET_ACCOUNT_ID | Prefix: $RESOURCE_PREFIX"
echo ""

# Step 1: Create roles in target account
echo "--- Step 1: Target account roles ---"
CREDS=$(aws sts assume-role --role-arn "arn:aws:iam::${TARGET_ACCOUNT_ID}:role/${RESOURCE_PREFIX}-cluster-mgmt-iam" --role-session-name setup 2>/dev/null || \
        aws sts assume-role --role-arn "arn:aws:iam::${TARGET_ACCOUNT_ID}:role/OrganizationAccountAccessRole" --role-session-name setup 2>/dev/null || \
        echo "")

if [ -z "$CREDS" ]; then
  echo "⚠️  Cannot assume role in target account. Run with --target-only from the target account first."
  echo "   Skipping step 1, continuing with hub configuration..."
else
  export AWS_ACCESS_KEY_ID=$(echo $CREDS | jq -r '.Credentials.AccessKeyId')
  export AWS_SECRET_ACCESS_KEY=$(echo $CREDS | jq -r '.Credentials.SecretAccessKey')
  export AWS_SESSION_TOKEN=$(echo $CREDS | jq -r '.Credentials.SessionToken')
  create_target_roles "$HUB_ACCOUNT_ID"
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
fi

# Step 2: Update hub ACK capability role
echo ""
echo "--- Step 2: Hub ACK capability role ($ACK_CAPABILITY_ROLE) ---"
EXISTING=$(aws iam get-role-policy --role-name "$ACK_CAPABILITY_ROLE" --policy-name AssumeWorkloadRoles --query 'PolicyDocument.Statement[0].Resource' --output json 2>/dev/null || echo '[]')
NEW_ARN="arn:aws:iam::${TARGET_ACCOUNT_ID}:role/${RESOURCE_PREFIX}-cluster-mgmt-*"

if echo "$EXISTING" | grep -q "$TARGET_ACCOUNT_ID"; then
  echo "  Target account already in AssumeWorkloadRoles"
else
  RESOURCES=$(echo "$EXISTING" | jq --arg new "$NEW_ARN" '. + [$new]')
  aws iam put-role-policy --role-name "$ACK_CAPABILITY_ROLE" --policy-name AssumeWorkloadRoles --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{\"Effect\": \"Allow\", \"Action\": [\"sts:AssumeRole\", \"sts:TagSession\"], \"Resource\": $RESOURCES}]
  }"
  echo "  ✅ Added target account to AssumeWorkloadRoles"
fi

aws iam put-role-policy --role-name "$ACK_CAPABILITY_ROLE" --policy-name secretsmanager-cross-account --policy-document '{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Action": ["secretsmanager:CreateSecret","secretsmanager:DeleteSecret","secretsmanager:DescribeSecret","secretsmanager:GetSecretValue","secretsmanager:ListSecrets","secretsmanager:PutSecretValue","secretsmanager:UpdateSecret","secretsmanager:TagResource"], "Resource": "*"}]
}'
echo "  ✅ Secretsmanager permissions configured"

# Step 3: Update hub ArgoCD capability role
echo ""
echo "--- Step 3: Hub ArgoCD capability role ($ARGOCD_CAPABILITY_ROLE) ---"
aws iam put-role-policy --role-name "$ARGOCD_CAPABILITY_ROLE" --policy-name "cross-account-eks-${TARGET_ACCOUNT_ID}" --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {\"Effect\": \"Allow\", \"Action\": [\"sts:AssumeRole\", \"sts:TagSession\"], \"Resource\": \"arn:aws:iam::${TARGET_ACCOUNT_ID}:role/${RESOURCE_PREFIX}-*-argocd-role\"},
    {\"Effect\": \"Allow\", \"Action\": [\"eks:DescribeCluster\", \"eks:ListClusters\", \"eks:AccessKubernetesApi\", \"eks:DescribeAccessEntry\", \"eks:ListAccessEntries\"], \"Resource\": \"arn:aws:eks:*:${TARGET_ACCOUNT_ID}:cluster/${RESOURCE_PREFIX}-*\"}
  ]
}"
echo "  ✅ Cross-account EKS permissions configured"

echo ""
echo "✅ Cross-account setup complete for account ${TARGET_ACCOUNT_ID}!"
echo "   You can now create clusters in this account via the Backstage template."
