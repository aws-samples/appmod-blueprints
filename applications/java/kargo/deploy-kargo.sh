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
  # Restart kargo controller to pick up the new credentials
  kubectl rollout restart deployment -n kargo 2>/dev/null || true
  kubectl rollout status deployment -n kargo --timeout=60s 2>/dev/null || true
fi

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

# Kargo Warehouse uses a Kubernetes Secret for ECR authentication when
# discovering image tags — Pod-Identity credentials are not consumed
# by the Warehouse controller. Create (or refresh) the ECR secret so
# the Warehouse can list tags without 401 Unauthorized errors.
# The ECR token expires after 12 h; the secret is re-created here each
# time deploy-kargo.sh is run, which covers re-runs and long events.
KARGO_NS="java-app-kargo"
ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/peeks/java"
echo "Creating Kargo ECR image credential secret..."
ECR_PWD=$(aws ecr get-login-password --region "$AWS_REGION")
kubectl -n "$KARGO_NS" delete secret ecr-creds --ignore-not-found >/dev/null 2>&1
kubectl -n "$KARGO_NS" create secret generic ecr-creds \
  --from-literal=repoURL="$ECR_REPO" \
  --from-literal=username=AWS \
  --from-literal=password="$ECR_PWD"
kubectl -n "$KARGO_NS" label secret ecr-creds kargo.akuity.io/cred-type=image --overwrite
echo "  ✓ ECR credential secret created"

# Deploy the promotion task
echo "Creating Kargo promotion task..."
envsubst < promotiontask.yaml | kubectl apply -f -

# Deploy the stages
echo "Creating Kargo stages..."
envsubst < stages.yaml | kubectl apply -f -

echo "Kargo configuration deployed successfully!"
echo "You can now access the Kargo UI to monitor promotions."