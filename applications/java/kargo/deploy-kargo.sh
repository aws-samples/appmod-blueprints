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

# Deploy the project (creates namespace)
echo "Creating Kargo project..."
envsubst < project.yaml | kubectl apply -f -

# Deploy the warehouse
echo "Creating Kargo warehouse..."
envsubst < warehouse.yaml | kubectl apply -f -

# Deploy the promotion task
echo "Creating Kargo promotion task..."
envsubst < promotiontask.yaml | kubectl apply -f -

# Deploy the stages
echo "Creating Kargo stages..."
envsubst < stages.yaml | kubectl apply -f -

# Deploy the git secrets
echo "Creating Kargo stages..."
envsubst < git-secret.yaml | kubectl apply -f -

echo "Kargo configuration deployed successfully!"
echo "You can now access the Kargo UI to monitor promotions."