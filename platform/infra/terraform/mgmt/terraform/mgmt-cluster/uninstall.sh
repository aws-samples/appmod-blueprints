#!/bin/bash
set -e -o pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
# source ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/utils.sh

echo -e "${PURPLE}\nTargets:${NC}"
echo "Kubernetes cluster: $(kubectl config current-context)"
echo "AWS profile (if set): ${AWS_PROFILE}"
echo "AWS account number: $(aws sts get-caller-identity --query "Account" --output text)"

SETUP_DIR="${REPO_ROOT}/platform/infra/terraform/mgmt/setups"

cd "${SETUP_DIR}/argocd/"
./uninstall.sh || true
cd -

cd "${REPO_ROOT}/platform/infra/terraform/mgmt/terraform/mgmt-cluster"

#kubectl delete -f ./karpenter.yaml || true
kubectl delete -f ./auto-mode.yaml || true


terraform destroy -auto-approve
