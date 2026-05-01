#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/../terraform"

echo "==> WARNING: This will destroy all resources including the EKS cluster."
read -r -p "Type 'yes' to confirm: " confirm
if [[ "${confirm}" != "yes" ]]; then
  echo "Aborted."
  exit 1
fi

echo "==> Destroying infrastructure..."
terraform -chdir="${TERRAFORM_DIR}" destroy -auto-approve

echo "==> Cleanup complete."
