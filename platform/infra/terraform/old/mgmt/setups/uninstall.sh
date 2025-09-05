#!/bin/bash
set -e -o pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
SETUP_DIR="${REPO_ROOT}/platform/infra/terraform/mgmt/setups"
TF_DIR="${REPO_ROOT}/platform/infra/terraform/mgmt/terraform"
source ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/utils.sh

cd ${SETUP_DIR}

echo -e "${PURPLE}\nTargets:${NC}"
echo "Kubernetes cluster: $(kubectl config current-context)"
echo "AWS profile (if set): ${AWS_PROFILE}"
echo "AWS account number: $(aws sts get-caller-identity --query "Account" --output text)"

cd "${TF_DIR}"
terraform destroy -auto-approve

#cd "${SETUP_DIR}/argocd/"
#./uninstall.sh
#cd -
