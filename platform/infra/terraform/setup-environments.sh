#!/bin/bash
#
# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

#title           create-workshop.sh
#description     This script sets up terraform EKS clusters and prerequisites
#version         1.0
#==============================================================================
set -e -o pipefail

# checking environment variables

if [ -z "${TF_VAR_aws_region}" ]; then
  message="env variable AWS_REGION not set, defaulting to us-west-2"
  echo $message
  export TF_VAR_aws_region="us-west-2"
fi

# SLR Required for Karpenter
if aws iam get-role --role-name AWSServiceRoleForEC2Spot >/dev/null 2>&1; then
  echo "EC2 Spot service role already exists, skipping creation."
else
  aws iam create-service-linked-role --aws-service-name spot.amazonaws.com
  echo "EC2 Spot service linked role created."
fi

export REPO_ROOT=$(git rev-parse --show-toplevel)
source ${REPO_ROOT}/platform/infra/terraform/setup-keycloak.sh


# Deploy the base cluster with prerequisites like ArgoCD and Ingress-nginx
${REPO_ROOT}/platform/infra/terraform/mgmt/terraform/mgmt-cluster/install.sh

# Set the DNS_HOSTNAME to be checked
export DNS_HOSTNAME=$(kubectl get service ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Replace dns with the value of DNS_HOSTNAME
sed -e "s/INGRESS_DNS/${DNS_HOSTNAME}/g" ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/default-config.yaml >${REPO_ROOT}/platform/infra/terraform/mgmt/setups/config.yaml

# Set Github URL for Management Cluster
export GITHUB_URL=$(yq '.repo_url' ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/config.yaml)
export GITHUB_BRANCH=$(yq '.repo_branch' ${REPO_ROOT}/platform/infra/terraform/mgmt/setups/config.yaml)


# Deploy the apps on IDP Builder and ArgoCD
${REPO_ROOT}/platform/infra/terraform/mgmt/setups/install.sh

cd ${REPO_ROOT}/platform/infra/terraform/mgmt/terraform/mgmt-cluster/
export TF_eks_cluster_vpc_id=$(terraform output -raw eks_cluster_vpc_id)
export TF_eks_cluster_private_subnets=$(terraform output -json eks_cluster_private_subnets)
export TF_eks_cluster_node_security_group_id=$(terrafrom output -raw eks_cluster_node_security_group_id)
echo "private subnets are : " $TF_eks_cluster_private_subnets
# For Database and EC2 database
export TF_eks_cluster_vpc_cidr=$(terraform output -raw vpc_cidr)
export TF_eks_cluster_private_az=$(terraform output -json availability_zones)
echo "private az are : " $TF_eks_cluster_private_az
export KEYCLOAK_NAMESPACE=keycloak
export KEYCLOAK_REALM=modernengg
export KEYCLOAK_USER_ADMIN_PASSWORD=$(openssl rand -base64 8)
export KEYCLOAK_USER_EDITOR_PASSWORD=$(openssl rand -base64 8)
export KEYCLOAK_USER_VIEWER_PASSWORD=$(openssl rand -base64 8)

# Set your secret values
export AMG_SECRET_NAME="modern-engg/amg"
export AMG_SECRET_VALUE="{\"amg-admin-password\":\"$KEYCLOAK_USER_ADMIN_PASSWORD\",\"amg-editor-password\":\"$KEYCLOAK_USER_EDITOR_PASSWORD\",\"amg-viewer-password\":\"$KEYCLOAK_USER_VIEWER_PASSWORD\"}"

# Check if the secret exists
if aws secretsmanager describe-secret --secret-id $AMG_SECRET_NAME --region $TF_VAR_aws_region &>/dev/null; then
  echo "Secret exists. Updating..."
  aws secretsmanager put-secret-value \
    --secret-id $AMG_SECRET_NAME \
    --secret-string "$AMG_SECRET_VALUE" \
    --region $TF_VAR_aws_region
  echo "Secret updated successfully."
else
  echo "Secret does not exist. Creating..."
  aws secretsmanager create-secret \
    --name $AMG_SECRET_NAME \
    --description "My secret description" \
    --secret-string "$AMG_SECRET_VALUE" \
    --region $TF_VAR_aws_region \
    --tags "Key=project,Value=modern-engg" --query "ARN"
  echo "Secret created successfully."
fi

# Default cluster names set. To override, set them as environment variables.
export TF_VAR_mgmt_cluster_name="modern-engineering"
export TF_VAR_dev_cluster_name="modernengg-dev"
export TF_VAR_prod_cluster_name="modernengg-prod"

# SAML IDP Metadata url for keycloak
export TF_VAR_grafana_keycloak_idp_url="http://${DNS_HOSTNAME}/keycloak/realms/${KEYCLOAK_REALM}/protocol/saml/descriptor"

echo "Following environment variables will be used:"
echo "CLUSTER_REGION = "$TF_VAR_aws_region
echo "DEV_CLUSTER_NAME = "$TF_VAR_dev_cluster_name
echo "PROD_CLUSTER_NAME = "$TF_VAR_prod_cluster_name
echo "VPC_ID = "$TF_eks_cluster_vpc_id
echo "VPC_Private_Subnets = "$TF_eks_cluster_private_subnets
echo "Grafana Keycloak IDP metadata URL = "$TF_VAR_grafana_keycloak_idp_url
echo "Github Source Repo for Management EKS Cluster =" $GITHUB_URL

# bootstrapping TF S3 bucket and DynamoDB locally
cd "${REPO_ROOT}/platform/infra/terraform/"

rm -rf terraform-aws-observability-accelerator/
git clone https://github.com/aws-observability/terraform-aws-observability-accelerator.git

echo "bootstrapping Terraform"
terraform -chdir=bootstrap init -reconfigure
terraform -chdir=bootstrap plan
terraform -chdir=bootstrap apply -auto-approve

export TF_VAR_state_s3_bucket=$(terraform -chdir=bootstrap output -raw eks-accelerator-bootstrap-state-bucket)
export TF_VAR_state_ddb_lock_table=$(terraform -chdir=bootstrap output -raw eks-accelerator-bootstrap-ddb-lock-table)
export TF_VAR_managed_prometheus_workspace_id=$(terraform -chdir=bootstrap output -raw amp_workspace_id)
export TF_VAR_managed_grafana_workspace_id=$(terraform -chdir=bootstrap output -raw amg_workspace_id)
export TF_VAR_grafana_workspace_endpoint=$(terraform -chdir=bootstrap output -raw grafana_workspace_endpoint)

export WORKSPACE_ENDPOINT=$TF_VAR_grafana_workspace_endpoint
export WORKSPACE_ID=$TF_VAR_managed_grafana_workspace_id

# Export the Keycloak admin password for the workspace from the Management Cluster Keycloak
export KEYCLOAK_ADMIN_PASSWORD=$(kubectl get secret keycloak-config -n keycloak --template={{.data.KEYCLOAK_ADMIN_PASSWORD}} | base64 -d)
export AWS_REGION=$TF_VAR_aws_region

# Configure Keycloak Realm for Grafana Workspace
configure_keycloak

# Update SAML Auth for Grafana Workspace
# update_workspace_saml_auth || true

cd "${REPO_ROOT}/platform/infra/terraform/"

# Bootstrap EKS Cluster using S3 bucket and DynamoDB
echo "Following bucket and dynamodb table will be used to store states for dev and PROD Cluster:"
echo "S3_BUCKET = "$TF_VAR_state_s3_bucket
echo "DYNAMO_DB_lOCK_TABLE = "$TF_VAR_state_ddb_lock_table

# Create API key for Managed Grafana and export the key.
export AMG_API_KEY=$(aws grafana create-workspace-api-key \
  --key-name "grafana-operator-${RANDOM}" \
  --key-role "ADMIN" \
  --seconds-to-live 432000 \
  --workspace-id $TF_VAR_managed_grafana_workspace_id \
  --query key \
  --output text)

echo "Following Managed Grafana Workspace used for Observability accelerator for both DEV and PROD:"
echo "Managed Grafana Workspace ID = "$TF_VAR_managed_grafana_workspace_id

echo "Following Amazon Managed Prometheus Workspace will be used for Observability accelerator for both DEV and PROD:"
echo "Managed Prometheus Workspace ID = "$TF_VAR_managed_prometheus_workspace_id

# Initialize backend for DB DEV cluster
terraform -chdir=dev/db init -reconfigure -backend-config="key=dev/db/db-ec2-cluster.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Apply the infrastructure changes to deploy DB DEV cluster
terraform -chdir=dev/db plan -var aws_region="${TF_VAR_aws_region}" \
  -var vpc_id="${TF_eks_cluster_vpc_id}" \
  -var vpc_private_subnets="${TF_eks_cluster_private_subnets}" \
  -var availability_zones="${TF_eks_cluster_private_az}" \
  -var vpc_cidr="${TF_eks_cluster_vpc_cidr}" \
  -var key_name="ws-default-keypair" -var region="${TF_VAR_aws_region}" -out=devdbplan

terraform -chdir=dev/db apply "devdbplan" &

export DEV_DB_PROCESS=$!

# Initialize backend for DEV cluster
terraform -chdir=dev init -reconfigure -backend-config="key=dev/eks-accelerator-vpc.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Apply the infrastructure changes to deploy EKS DEV cluster and install EKS observability Accelerator
terraform -chdir=dev plan -var aws_region="${TF_VAR_aws_region}" \
  -var managed_grafana_workspace_id="${TF_VAR_managed_grafana_workspace_id}" \
  -var managed_prometheus_workspace_id="${TF_VAR_managed_prometheus_workspace_id}" \
  -var cluster_name="${TF_VAR_dev_cluster_name}" \
  -var vpc_id="${TF_eks_cluster_vpc_id}" \
  -var vpc_private_subnets="${TF_eks_cluster_private_subnets}" \
  -var grafana_api_key="${AMG_API_KEY}"  -out=devplan

terraform -chdir=dev apply "devplan" &

export DEV_EKS_PROCESS=$!


# Initialize backend for PROD cluster
terraform -chdir=prod init -reconfigure -backend-config="key=prod/eks-accelerator-vpc.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Apply the infrastructure changes to deploy EKS PROD cluster and deploy observability accelerator
terraform -chdir=prod plan -var aws_region="${TF_VAR_aws_region}" \
  -var managed_grafana_workspace_id="${TF_VAR_managed_grafana_workspace_id}" \
  -var managed_prometheus_workspace_id="${TF_VAR_managed_prometheus_workspace_id}" \
  -var cluster_name="${TF_VAR_prod_cluster_name}" \
  -var vpc_id="${TF_eks_cluster_vpc_id}" \
  -var vpc_private_subnets="${TF_eks_cluster_private_subnets}" \
  -var grafana_api_key="${AMG_API_KEY}" -out=prodplan

terraform  -chdir=prod apply "prodplan" &

export PROD_EKS_PROCESS=$!
# Wait for both processes to complete
echo "DEV DB Process PID: $DEV_DB_PROCESS"
echo "DEV EKS Process PID: $DEV_EKS_PROCESS"
echo "PROD EKS Process PID: $PROD_EKS_PROCESS"
wait $DEV_DB_PROCESS $DEV_EKS_PROCESS $PROD_EKS_PROCESS

export DEV_CP_ROLE_ARN=$(terraform -chdir=dev output -raw crossplane_dev_provider_role_arn)
export DEV_ACK_ROLE_ARN=$(terraform -chdir=dev output -raw ack_dev_controller_role_arn)
export DEV_ARGOROLL_ROLE_ARN=$(terraform -chdir=dev output -raw argo_rollouts_dev_role_arn)
export LB_DEV_ROLE_ARN=$(terraform -chdir=dev output -raw lb_controller_dev_role_arn)

export PROD_CP_ROLE_ARN=$(terraform -chdir=prod output -raw crossplane_prod_provider_role_arn)
export PROD_ACK_ROLE_ARN=$(terraform -chdir=prod output -raw ack_prod_controller_role_arn)
export PROD_ARGOROLL_ROLE_ARN=$(terraform -chdir=prod output -raw argo_rollouts_prod_role_arn)
export LB_PROD_ROLE_ARN=$(terraform -chdir=prod output -raw lb_controller_prod_role_arn)

# Change IAM Access Configs for DEV Cluster
aws eks --region $TF_VAR_aws_region update-kubeconfig --name $TF_VAR_dev_cluster_name
export DEV_ACCESS_CONF=$(aws eks describe-cluster --region $TF_VAR_aws_region --name $TF_VAR_dev_cluster_name --query 'cluster.accessConfig' --output text)

if [[ "$DEV_ACCESS_CONF" != "API_AND_CONFIG_MAP" ]]; then
  echo "Changing IAM access configs for DEV cluster: $DEV_ACCESS_CONF"
  aws eks update-cluster-config --region $TF_VAR_aws_region --name ${TF_VAR_dev_cluster_name} --access-config authenticationMode=API_AND_CONFIG_MAP || true
fi

# Change IAM Access Configs for PROD Cluster
aws eks --region $TF_VAR_aws_region update-kubeconfig --name $TF_VAR_prod_cluster_name
export PROD_ACCESS_CONF=$(aws eks describe-cluster --region $TF_VAR_aws_region --name $TF_VAR_prod_cluster_name --query 'cluster.accessConfig' --output text)
if [[ "$PROD_ACCESS_CONF" != "API_AND_CONFIG_MAP" ]]; then
  echo "Changing IAM access configs for PROD cluster: $PROD_ACCESS_CONF"
  aws eks update-cluster-config --region $TF_VAR_aws_region --name $TF_VAR_prod_cluster_name --access-config authenticationMode=API_AND_CONFIG_MAP || true
  echo "Sleeping for 3 minutes to allow cluster to change auth mode"
  sleep 180
fi

# Reconnect back to Management Cluster
aws eks --region $TF_VAR_aws_region update-kubeconfig --name $TF_VAR_mgmt_cluster_name

# Setup Kubevela on Management,Dev and Prod clusters and deploy crossplane AWS providers

sed -e "s#DEV_CP_ROLE_ARN#${DEV_CP_ROLE_ARN}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/crossplane-aws-drc-dev.yaml > ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/crossplane-aws-drc-dev.yml
sed -e "s#PROD_CP_ROLE_ARN#${PROD_CP_ROLE_ARN}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/crossplane-aws-drc-prod.yaml > ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/crossplane-aws-drc-prod.yml

# Setup ACK ServiceAccount and Role
sed -e "s#DEV_ACK_ROLE_ARN#${DEV_ACK_ROLE_ARN}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/ack-aws-irsa-dev.yaml > ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/ack-aws-irsa-dev.yml
sed -e "s#PROD_ACK_ROLE_ARN#${PROD_ACK_ROLE_ARN}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/ack-aws-irsa-prod.yaml > ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/ack-aws-irsa-prod.yml

# Setup AWS LB controller configs and roles
sed -e "s#DEV_LB_ROLE_ARN#${LB_DEV_ROLE_ARN}#g" -e "s#DEV_CLUSTER_NAME#${TF_VAR_dev_cluster_name}#g" -e "s#DEV_EKS_VPC_ID#${TF_eks_cluster_vpc_id}#g" -e "s#DEV_EKS_REGION#${TF_VAR_aws_region}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/aws-lb-controller-dev.yaml > ${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/aws-lb-controller-dev.yml
sed -e "s#PROD_LB_ROLE_ARN#${LB_PROD_ROLE_ARN}#g" -e "s#PROD_CLUSTER_NAME#${TF_VAR_prod_cluster_name}#g" -e "s#PROD_EKS_VPC_ID#${TF_eks_cluster_vpc_id}#g" -e "s#PROD_EKS_REGION#${TF_VAR_aws_region}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/aws-lb-controller-prod.yaml > ${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/aws-lb-controller-prod.yml

# Setup Argo-Rollouts configs and roles
sed -e "s#DEV_ARGOROLL_ROLE_ARN#${DEV_ARGOROLL_ROLE_ARN}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/argorollouts-dev.yaml > ${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/argorollouts-dev.yml
sed -e "s#PROD_ARGOROLL_ROLE_ARN#${PROD_ARGOROLL_ROLE_ARN}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/argorollouts-prod.yaml > ${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/argorollouts-prod.yml

# Connect ArgoCD on MGMT cluster to DEV and PROD target clusters
terraform -chdir=post-deploy init -reconfigure -backend-config="key=post/argocd-connect-vpc.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

export TF_VAR_GITEA_URL="https://${DNS_HOSTNAME}/gitea"

# Apply the changes for ArgoConnect and Codebuild project for clusters
terraform -chdir=post-deploy apply -var aws_region="${TF_VAR_aws_region}" \
  -var mgmt_cluster_gitea_url="${TF_VAR_GITEA_URL}" \
  -var dev_cluster_name="${TF_VAR_dev_cluster_name}" \
  -var prod_cluster_name="${TF_VAR_prod_cluster_name}" -auto-approve

NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
NODE_PORT=$(kubectl get service devlake-mysql -n devlake -o jsonpath='{.spec.ports[0].nodePort}')
export DEVLAKE_MYSQL_NODEPORT="${NODE_IP}:${NODE_PORT}"

# Setup Applications on Clusters using ArgoCD on the management cluster

# Substitute the GITHUB_URL and GITHUB_BRANCH in the manifests
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/ack-dev.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/ack-dev.yml
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/ack-prod.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/ack-prod.yml
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/crossplane-comp-dev.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/crossplane-comp-dev.yml
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/crossplane-comp-prod.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/crossplane-comp-prod.yml
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/crossplane-provider-dev.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/crossplane-provider-dev.yml
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/crossplane-provider-prod.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/crossplane-provider-prod.yml
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" -e "s#\${NODEPORT_ENDPOINT}#${DEVLAKE_MYSQL_NODEPORT}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/grafana-workload-dashboards.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/grafana-workload-dashboards.yml
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/kubevela-dev.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/kubevela-dev.yml
sed -e "s#\${GITHUB_URL}#${GITHUB_URL}#g" -e "s#\${GITHUB_BRANCH}#${GITHUB_BRANCH}#g" ${REPO_ROOT}/platform/infra/terraform/deploy-apps/kubevela-prod.yaml >${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/kubevela-prod.yml

# Apply the manifests to the management cluster
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/manifests/

# Setup Gitea Repo
${REPO_ROOT}/platform/infra/terraform/giteaInit.sh

# Add AMG URL to Devlake
kubectl set env deployment devlake-ui GRAFANA_ENDPOINT="https://$WORKSPACE_ENDPOINT/" -n devlake
# Sleeping for Crossplane to be ready in DEV and PROD Cluster and restarting backstage pod
kubectl rollout restart deployment backstage -n backstage
sleep 120

# Setup CrossPlane IRSA for DEV Cluster
aws eks --region $TF_VAR_aws_region update-kubeconfig --name $TF_VAR_dev_cluster_name
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/crossplane-aws-drc-dev.yml
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/cp-dev-env-config.yaml
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/cluster-secret-store.yaml
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/ack-aws-irsa-dev.yml

# Setup CrossPlane IRSA for PROD Cluster
aws eks --region $TF_VAR_aws_region update-kubeconfig --name $TF_VAR_prod_cluster_name
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/crossplane-aws-drc-prod.yml
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/cp-prod-env-config.yaml
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/cluster-secret-store.yaml
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/drc/ack-aws-irsa-prod.yml

# Clean git folder inside the terraform folder to avoid conflicts
rm -rf ${REPO_ROOT}/platform/infra/terraform/.git || true

echo "Terraform execution completed"

# Cleanup Folders
rm -rf terraform-aws-observability-accelerator/

# Switching context to MGMT cluster
aws eks --region $TF_VAR_aws_region update-kubeconfig --name $TF_VAR_mgmt_cluster_name

# Print all Outputs

echo "ArgoCD URL is: https://$DNS_HOSTNAME/argocd"

echo "GITEA URL is: https://$DNS_HOSTNAME/gitea"

echo "Keycloak URL is: https://$DNS_HOSTNAME/keycloak"

echo "Backstage URL is: https://$DNS_HOSTNAME/"

echo "ArgoWorkflows URL is: https://$DNS_HOSTNAME/argo-workflows"

echo "-------------------"
echo "Amazon Managed Grafana Workspace endpoint: https://$WORKSPACE_ENDPOINT/"
echo "-------------------"
echo "Amazon Managed Grafana Admin Credentials"
echo "-------------------"
echo "username: monitor-admin"
echo "password: $KEYCLOAK_USER_ADMIN_PASSWORD"
echo ""
echo "-------------------"
echo "Amazon Managed Grafana Editor Credentials"
echo "-------------------"
echo "username: monitor-editor"
echo "password: $KEYCLOAK_USER_EDITOR_PASSWORD"
echo ""
echo "-------------------"
echo "Amazon Managed Grafana Viewer Credentials"
echo "-------------------"
echo "username: monitor-viewer"
echo "password: $KEYCLOAK_USER_VIEWER_PASSWORD"
echo ""
echo "Setup done."

echo "Script Complete"
