#!/bin/bash
set -e

echo "Creating IAM role and pod identity association for Strands agent test"

# Get AWS account ID and region
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region || echo "us-west-2")

# Get cluster name (you may need to adjust this)
CLUSTER_NAME=${CLUSTER_NAME:-$(kubectl config current-context | cut -d'/' -f2 | cut -d'.' -f1)}

echo "Account ID: $ACCOUNT_ID"
echo "Region: $REGION"
echo "Cluster: $CLUSTER_NAME"
echo ""

# Create trust policy for EKS Pod Identity
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

# Create IAM role with no permissions
ROLE_NAME="strands-agent-test-role"

echo "Creating role: $ROLE_NAME"
aws iam create-role \
  --role-name $ROLE_NAME \
  --assume-role-policy-document file:///tmp/trust-policy.json \
  --description "Test role for Strands agent - no permissions" \
  2>/dev/null || echo "Role already exists"

# Get role ARN
ROLE_ARN=$(aws iam get-role --role-name $ROLE_NAME --query 'Role.Arn' --output text)

echo "Role ARN: $ROLE_ARN"
echo ""

# Create pod identity association
echo "Creating pod identity association..."
aws eks create-pod-identity-association \
  --cluster-name $CLUSTER_NAME \
  --namespace default \
  --service-account strands-agent-test-sa \
  --role-arn $ROLE_ARN \
  --region $REGION \
  2>/dev/null || echo "Association already exists"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Role ARN: $ROLE_ARN"
echo ""
echo "Update test-pod.yaml ServiceAccount annotation with:"
echo "  eks.amazonaws.com/role-arn: $ROLE_ARN"
echo ""
echo "Or use this command:"
echo "kubectl annotate serviceaccount strands-agent-test-sa -n default eks.amazonaws.com/role-arn=$ROLE_ARN --overwrite"

# Clean up
rm /tmp/trust-policy.json
