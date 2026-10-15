#!/bin/bash

# Deploy Kargo configuration for Java application
# This script applies the Kargo configuration with environment variable substitution

set -e

echo "Deploying Kargo configuration for Java application..."

# Check if required environment variables are set
if [[ -z "$AWS_ACCOUNT_ID" || -z "$AWS_REGION" || -z "$GITLAB_URL" || -z "$GIT_USERNAME" ]]; then
    echo "Error: Required environment variables are not set."
    echo "Please ensure the following variables are set:"
    echo "  - AWS_ACCOUNT_ID"
    echo "  - AWS_REGION" 
    echo "  - GITLAB_URL"
    echo "  - GIT_USERNAME"
    exit 1
fi

# Ensure RESOURCE_PREFIX is exported so envsubst resolves ${RESOURCE_PREFIX} in the
# kargo manifests (warehouse/stages/promotiontask) to the correct ECR repo.
export RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"

# Ensure the Kargo controller has ECR read access so the warehouse can discover images.
# Creates the IAM role + pod identity association (idempotent).
HUB_CLUSTER="${RESOURCE_PREFIX:-peeks}-hub"
KARGO_ROLE="${HUB_CLUSTER}-kargo-controller-role"

echo "Setting up Kargo ECR access..."
if ! aws iam get-role --role-name "$KARGO_ROLE" --region "$AWS_REGION" >/dev/null 2>&1; then
  aws iam create-role --role-name "$KARGO_ROLE" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"pods.eks.amazonaws.com"},"Action":["sts:AssumeRole","sts:TagSession"]}]}' \
    --description "Kargo controller ECR read access" --no-cli-pager >/dev/null
  aws iam attach-role-policy --role-name "$KARGO_ROLE" \
    --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly --region "$AWS_REGION"
  echo "  ✓ IAM role $KARGO_ROLE created"
fi
KARGO_ROLE_ARN=$(aws iam get-role --role-name "$KARGO_ROLE" --query 'Role.Arn' --output text --region "$AWS_REGION")
if ! aws eks list-pod-identity-associations --cluster-name "$HUB_CLUSTER" --region "$AWS_REGION" \
  --query "associations[?namespace=='kargo'&&serviceAccount=='kargo-controller']" --output text 2>/dev/null | grep -q .; then
  aws eks create-pod-identity-association \
    --cluster-name "$HUB_CLUSTER" --namespace kargo --service-account kargo-controller \
    --role-arn "$KARGO_ROLE_ARN" --region "$AWS_REGION" >/dev/null
  echo "  ✓ pod identity association created"
fi

# The Warehouse lists ECR tags with this pod identity (Kargo's ECR "ambient
# credentials": Kargo gets and refreshes the 12 h ECR tokens itself). The
# controller reads the identity once, at start-up, and a new role/association
# takes a few seconds to apply, so restart it until it starts with working
# AWS credentials.
kargo_has_aws_identity() {
  kubectl -n kargo get pods -l app.kubernetes.io/component=controller \
    -o jsonpath='{.items[*].spec.containers[*].env[*].name}' | grep -qw AWS_CONTAINER_CREDENTIALS_FULL_URI &&
  ! kubectl -n kargo logs deployment/kargo-controller 2>/dev/null | grep -q "AWS credentials integration will be disabled"
}
for _ in 1 2 3; do
  kargo_has_aws_identity && break
  sleep 15
  kubectl -n kargo rollout restart deployment kargo-controller 2>/dev/null || true
  kubectl -n kargo rollout status deployment kargo-controller --timeout=120s 2>/dev/null || true
done
kargo_has_aws_identity || echo "  ! kargo-controller has no working pod identity; the Warehouse can't list ECR images"

# Deploy the project (creates namespace)
echo "Creating Kargo project..."
envsubst < project.yaml | kubectl apply -f -

# Deploy the git secrets
echo "Creating Kargo stages..."
envsubst < git-secret.yaml | kubectl apply -f -

# sleep for secret to be created first
sleep 10

# Deploy the warehouse
echo "Creating Kargo warehouse..."
envsubst < warehouse.yaml | kubectl apply -f -

# Earlier versions of this script stored a static ECR token in an `ecr-creds`
# Secret. Kargo uses a matching Secret instead of the pod identity, and that
# token expires after 12 h, so remove it.
kubectl -n java-app-kargo delete secret ecr-creds --ignore-not-found

# Deploy the promotion task
echo "Creating Kargo promotion task..."
envsubst < promotiontask.yaml | kubectl apply -f -

# Deploy the stages
echo "Creating Kargo stages..."
envsubst < stages.yaml | kubectl apply -f -

echo "Kargo configuration deployed successfully!"
echo "You can now access the Kargo UI to monitor promotions."