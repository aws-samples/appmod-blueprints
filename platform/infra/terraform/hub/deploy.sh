#!/usr/bin/env bash

#DEBUG=1 $BASE_DIR/platform/infra/terraform/hub/deploy.sh --cluster-name ${CLUSTER_NAME}

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

TF_VAR_FILE=${TF_VAR_FILE:-"terraform.tfvars"}

# Parse command line arguments
CLUSTER_NAME=""

while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    --cluster-name)
      CLUSTER_NAME="$2"
      shift
      shift
      ;;
    *)
      shift
      ;;
  esac
done

# Initialize Terraform
if [[ -n "${TFSTATE_BUCKET_NAME:-}" && -n "${TFSTATE_LOCK_TABLE:-}" ]]; then
  terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${TFSTATE_BUCKET_NAME}" -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}"
else
  terraform -chdir=$SCRIPTDIR init --upgrade
  echo "WARNING: TFSTATE_BUCKET_NAME and/or TFSTATE_LOCK_TABLE environment variables not set."
  echo "WARNING: Terraform state will be stored locally and may be lost!"
fi

echo "Deploy Hub cluster"

# Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Using AWS Account ID: $AWS_ACCOUNT_ID"

# Apply with custom cluster name if provided
if [ -n "$CLUSTER_NAME" ]; then
  echo "Using custom cluster name: $CLUSTER_NAME"
  terraform -chdir=$SCRIPTDIR apply -var-file=$TF_VAR_FILE -var="cluster_name=$CLUSTER_NAME" -var="account_ids=$AWS_ACCOUNT_ID" -auto-approve
else
  echo "Using default cluster name: peeks-hub-cluster"
  terraform -chdir=$SCRIPTDIR apply -var-file=$TF_VAR_FILE -var="account_ids=$AWS_ACCOUNT_ID" -auto-approve
fi
