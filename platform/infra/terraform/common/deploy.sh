#!/usr/bin/env bash

set -euo pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOTDIR="$(cd ${SCRIPTDIR}/../..; pwd )"
[[ -n "${DEBUG:-}" ]] && set -x


# Initialize Terraform
if [[ -n "${TFSTATE_BUCKET_NAME:-}" && -n "${TFSTATE_LOCK_TABLE:-}" ]]; then
  terraform -chdir=$SCRIPTDIR init --upgrade -backend-config="bucket=${TFSTATE_BUCKET_NAME}" -backend-config="dynamodb_table=${TFSTATE_LOCK_TABLE}"
else
  terraform -chdir=$SCRIPTDIR init --upgrade
  echo "WARNING: TFSTATE_BUCKET_NAME and/or TFSTATE_LOCK_TABLE environment variables not set."
  echo "WARNING: Terraform state will be stored locally and may be lost!"
fi

echo "Applying git resources"

terraform -chdir=$SCRIPTDIR apply -auto-approve


if [[ ${PIPESTATUS[0]} -eq 0 ]]; then
  # wait for ssh access allowed
  sleep 10
  echo "SUCCESS: Terraform apply of all modules completed successfully"
else
  echo "FAILED: Terraform apply of all modules failed"
  exit 1
fi

