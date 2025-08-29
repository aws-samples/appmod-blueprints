#!/usr/bin/env bash

#usage:
#DEBUG=1 $BASE_DIR/platform/infra/terraform/spokes/deploy.sh ${SPOKE} --cluster-name-prefix ${CLUSTER_NAME_PREFIX}

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

if [[ $# -eq 0 ]] ; then
    echo "No arguments supplied"
    echo "Usage: deploy.sh <environment> [--cluster-name-prefix <prefix>] [--deploy-db]"
    echo "Example: deploy.sh dev"
    echo "Example with database: deploy.sh dev --deploy-db"
    echo "Example with custom cluster name prefix: deploy.sh dev --cluster-name-prefix peeks-spoke-test --deploy-db"
    echo ""
    echo "Required environment variables:"
    echo "  TFSTATE_BUCKET_NAME - S3 bucket for Terraform state"
    echo "  AWS_REGION - AWS region for resources"
    exit 1
fi

# Check required environment variables
if [[ -z "${TFSTATE_BUCKET_NAME:-}" ]]; then
    echo "Error: TFSTATE_BUCKET_NAME environment variable is required"
    exit 1
fi

if [[ -z "${AWS_REGION:-}" ]]; then
    echo "Error: AWS_REGION environment variable is required"
    exit 1
fi

env=$1
shift

# Parse additional command line arguments
CLUSTER_NAME_PREFIX=""
DEPLOY_DB=false

while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    --cluster-name-prefix)
      CLUSTER_NAME_PREFIX="$2"
      shift
      shift
      ;;
    --deploy-db)
      DEPLOY_DB=true
      shift
      ;;
    *)
      shift
      ;;
  esac
done

echo "Using S3 bucket: ${TFSTATE_BUCKET_NAME}"
echo "Using AWS region: ${AWS_REGION}"
echo "Deploying $env with workspaces/${env}.tfvars ..."

# Wait for GitLab CloudFront distribution to be created by hub cluster
echo "Waiting for GitLab CloudFront distribution to be created by hub cluster..."
GITLAB_DOMAIN=""
MAX_ATTEMPTS=30
ATTEMPT=0

while [[ $ATTEMPT -lt $MAX_ATTEMPTS ]]; do
    echo "Attempt $((ATTEMPT + 1))/$MAX_ATTEMPTS: Checking for GitLab CloudFront distribution..."
    
    # Check for GitLab distribution
    GITLAB_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'gitlab')].DomainName | [0]" --output text 2>/dev/null || echo "None")
    
    if [[ "$GITLAB_DOMAIN" != "None" && -n "$GITLAB_DOMAIN" ]]; then
        echo "✓ Found GitLab CloudFront distribution: ${GITLAB_DOMAIN}"
        break
    fi
    
    if [[ $ATTEMPT -eq $((MAX_ATTEMPTS - 1)) ]]; then
        echo "⚠️  Warning: GitLab CloudFront distribution not found after $MAX_ATTEMPTS attempts"
        echo "   GitLab domain: ${GITLAB_DOMAIN}"
        echo "   Continuing with empty value..."
        GITLAB_DOMAIN=""
        break
    fi
    
    echo "   Waiting 30 seconds before next attempt..."
    sleep 30
    ATTEMPT=$((ATTEMPT + 1))
done

# Deploy database first if requested
if [ "$DEPLOY_DB" = true ]; then
  echo "Deploying database for $env environment..."
  
  terraform -chdir=${SCRIPTDIR}/db init -reconfigure \
    -backend-config="bucket=${TFSTATE_BUCKET_NAME}" \
    -backend-config="key=spokes/db/${env}/terraform.tfstate" \
    -backend-config="region=${AWS_REGION}"
  
  terraform -chdir=${SCRIPTDIR}/db workspace select -or-create $env
  
  if [ -n "$CLUSTER_NAME_PREFIX" ]; then
    terraform -chdir=${SCRIPTDIR}/db apply -var-file="../workspaces/${env}.tfvars" -var="cluster_name_prefix=$CLUSTER_NAME_PREFIX" -auto-approve
  else
    terraform -chdir=${SCRIPTDIR}/db apply -var-file="../workspaces/${env}.tfvars" -auto-approve
  fi
  
  echo "Database deployment completed for $env"
fi

# Deploy EKS cluster
echo "Deploying EKS cluster for $env environment..."

if [[ -n "${TFSTATE_BUCKET_NAME:-}" && -n "${TFSTATE_LOCK_TABLE:-}" ]]; then
  terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${TFSTATE_BUCKET_NAME}" -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}"
else
  terraform -chdir=$SCRIPTDIR init --upgrade
  echo "WARNING: TFSTATE_BUCKET_NAME and/or TFSTATE_LOCK_TABLE environment variables not set."
  echo "WARNING: Terraform state will be stored locally and may be lost!"
fi
terraform -chdir=$SCRIPTDIR workspace select -or-create $env

# Apply with custom cluster name prefix if provided
if [ -n "$CLUSTER_NAME_PREFIX" ]; then
  echo "Using custom cluster name prefix: $CLUSTER_NAME_PREFIX"
  terraform -chdir=$SCRIPTDIR apply \
    -var-file="workspaces/${env}.tfvars" \
    -var="cluster_name_prefix=$CLUSTER_NAME_PREFIX" \
    -var="git_hostname=$GITLAB_DOMAIN" \
    -var="gitlab_domain_name=$GITLAB_DOMAIN" \
    -auto-approve
else
  echo "Using default cluster name prefix: peeks-spoke"
  terraform -chdir=$SCRIPTDIR apply \
    -var-file="workspaces/${env}.tfvars" \
    -var="git_hostname=$GITLAB_DOMAIN" \
    -var="gitlab_domain_name=$GITLAB_DOMAIN" \
    -auto-approve
fi
