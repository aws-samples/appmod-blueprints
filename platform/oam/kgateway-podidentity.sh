#!/bin/bash
set -e

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-west-2}"
CLUSTER_NAME="${CLUSTER_NAME:-hub}"

echo "Creating Pod Identity for agentgateway-proxy service account..."

# Create Bedrock IAM policy
cat > /tmp/bedrock-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ListFoundationModels",
        "bedrock:GetFoundationModel"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# Create IAM policy
POLICY_ARN=$(aws iam create-policy \
  --policy-name AgentGatewayBedrockPolicy \
  --policy-document file:///tmp/bedrock-policy.json \
  --query 'Policy.Arn' \
  --output text 2>&1)

if [[ $POLICY_ARN == *"EntityAlreadyExists"* ]]; then
  POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/AgentGatewayBedrockPolicy"
  echo "Policy already exists: $POLICY_ARN"
else
  echo "Policy created: $POLICY_ARN"
fi

# Create trust policy for Pod Identity
cat > /tmp/trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "pods.eks.amazonaws.com"
      },
      "Action": [
        "sts:AssumeRole",
        "sts:TagSession"
      ]
    }
  ]
}
EOF

# Create IAM role
ROLE_ARN=$(aws iam create-role \
  --role-name AgentGatewayBedrockRole \
  --assume-role-policy-document file:///tmp/trust-policy.json \
  --query 'Role.Arn' \
  --output text 2>&1)

if [[ $ROLE_ARN == *"EntityAlreadyExists"* ]]; then
  ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/AgentGatewayBedrockRole"
  echo "Role already exists: $ROLE_ARN"
else
  echo "Role created: $ROLE_ARN"
fi

# Attach policy to role
aws iam attach-role-policy \
  --role-name AgentGatewayBedrockRole \
  --policy-arn $POLICY_ARN

echo "Role ARN: $ROLE_ARN"

# Create Pod Identity association
aws eks create-pod-identity-association \
  --cluster-name $CLUSTER_NAME \
  --namespace agentgateway-system \
  --service-account agentgateway-proxy \
  --role-arn $ROLE_ARN \
  --region $REGION

echo "Pod Identity association created for agentgateway-proxy"
echo "Restart pods to apply: kubectl rollout restart deployment -n agentgateway-system"
