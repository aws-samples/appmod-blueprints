#!/usr/bin/env bash

set -uo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x

echo "Destroying AWS git and iam resources"
if [[ -n "${TFSTATE_BUCKET_NAME:-}" && -n "${TFSTATE_LOCK_TABLE:-}" ]]; then
  terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${TFSTATE_BUCKET_NAME}" -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}"
else
  # Try to get backend config from SSM parameters
  BUCKET_NAME=$(aws ssm get-parameter --name tf-backend-bucket --query 'Parameter.Value' --output text 2>/dev/null || echo "")
  LOCK_TABLE=$(aws ssm get-parameter --name tf-backend-lock-table --query 'Parameter.Value' --output text 2>/dev/null || echo "")
  
  if [[ -n "$BUCKET_NAME" && -n "$LOCK_TABLE" ]]; then
    terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${BUCKET_NAME}" -backend-config="dynamodb_table=${LOCK_TABLE}"
  else
    terraform -chdir=$SCRIPTDIR init --upgrade
    echo "WARNING: Backend configuration not found in environment variables or SSM parameters."
    echo "WARNING: Terraform state will be stored locally and may be lost!"
  fi
fi
terraform -chdir=$SCRIPTDIR destroy -auto-approve
destroy_output=$(terraform -chdir=$SCRIPTDIR  destroy -auto-approve 2>&1)

# Delete parameter created in the bootstrap
# aws ssm delete-parameter --name GiteaExternalUrl || true
