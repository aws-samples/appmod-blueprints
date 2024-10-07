#!/bin/bash
set -e -o pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)

source ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/utils.sh

echo -e "${GREEN}Installing with the following options: ${NC}"
echo -e "${GREEN}----------------------------------------------------${NC}"
yq '... comments=""' ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/config.yaml
echo -e "${GREEN}----------------------------------------------------${NC}"
echo -e "${PURPLE}\nTargets:${NC}"
echo "Kubernetes cluster: $(kubectl config current-context)"
echo "AWS profile (if set): ${AWS_PROFILE}"
echo "AWS account number: $(aws sts get-caller-identity --query "Account" --output text)"

export GITHUB_URL=$(yq '.repo_url' ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/config.yaml)
#
## Set up ArgoCD. We will use ArgoCD to install all components.
#cd "${REPO_ROOT}/setups/argocd/"
#./install.sh
#cd -

# The rest of the steps are defined as a Terraform module. Parse the config to JSON and use it as the Terraform variable file. This is done because JSON doesn't allow you to easily place comments.
cd "${REPO_ROOT}/platform/infra/terraform/mgmt/terraform/"
yq -o json '.'  ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/config.yaml > ${REPO_ROOT}/platform/infra/terraform/mgmt/terraform/terraform.tfvars.json
terraform init -upgrade
terraform apply -auto-approve
