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

#title           destroy-environments.sh
#description     This script deletes all terraform EKS clusters and prerequisites
#version         1.0
#==============================================================================

# checking environment variables

if [ -z "${TF_VAR_aws_region}" ]; then
    message="env variable AWS_REGION not set, defaulting to us-west-2"
    echo $message
    export TF_VAR_aws_region="us-west-2"
fi

REPO_ROOT=$(git rev-parse --show-toplevel)

# Default cluster names set. To override, set them as environment variables.
export TF_VAR_dev_cluster_name="modernengg-dev"
export TF_VAR_prod_cluster_name="modernengg-prod"

echo "Following environment variables will be used:"
echo "CLUSTER_REGION = "$TF_VAR_aws_region
echo "DEV_CLUSTER_NAME = "$TF_VAR_dev_cluster_name
echo "PROD_CLUSTER_NAME = "$TF_VAR_prod_cluster_name

rm -rf terraform-aws-observability-accelerator/
git clone https://github.com/aws-observability/terraform-aws-observability-accelerator.git

# bootstrapping TF S3 bucket and DynamoDB locally
echo "bootstrapping Terraform"
terraform -chdir=bootstrap init -reconfigure

export TF_VAR_state_s3_bucket=$(terraform -chdir=bootstrap  output -raw eks-accelerator-bootstrap-state-bucket)
export TF_VAR_state_ddb_lock_table=$(terraform -chdir=bootstrap output -raw eks-accelerator-bootstrap-ddb-lock-table)
export TF_VAR_managed_grafana_workspace_id=$(terraform -chdir=bootstrap output -raw amg_workspace_id)
export TF_VAR_managed_prometheus_workspace_id=$(terraform -chdir=bootstrap output -raw amp_workspace_id)

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

cd ${REPO_ROOT}/platform/infra/terraform/mgmt/terraform/mgmt-cluster/
export TF_eks_cluster_vpc_id=$(terraform output -raw eks_cluster_vpc_id)
export TF_eks_cluster_private_subnets=$(terraform output -json eks_cluster_private_subnets)
export TF_eks_cluster_vpc_cidr=$(terraform output -raw vpc_cidr)
export TF_eks_cluster_private_az=$(terraform output -json availability_zones)

aws eks --region $TF_VAR_aws_region update-kubeconfig --name modern-engineering

cd ${REPO_ROOT}/platform/infra/terraform/

# Connect ArgoCD on MGMT cluster to DEV and PROD target clusters
terraform -chdir=post-deploy init -reconfigure -backend-config="key=post/argocd-connect-vpc.tfstate" \
-backend-config="bucket=$TF_VAR_state_s3_bucket" \
-backend-config="region=$TF_VAR_aws_region" \
-backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Apply the infrastructure changes to deploy EKS DEV cluster and install EKS observability Accelerator
terraform -chdir=post-deploy destroy -var aws_region="${TF_VAR_aws_region}" -auto-approve

cd ${REPO_ROOT}/platform/infra/terraform/

# Initialize backend for DB DEV cluster
terraform -chdir=dev/db init -reconfigure -backend-config="key=dev/db/db-ec2-cluster.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Destroy the infrastructure changes to deploy DB DEV cluster
terraform -chdir=dev/db plan -destroy -var aws_region="${TF_VAR_aws_region}" \
  -var vpc_id="${TF_eks_cluster_vpc_id}" \
  -var vpc_private_subnets="${TF_eks_cluster_private_subnets}" \
  -var availability_zones="${TF_eks_cluster_private_az}" \
  -var vpc_cidr="${TF_eks_cluster_vpc_cidr}" \
  -var key_name="ws-default-keypair" -out=devdbdestroyplan

terraform -chdir=dev/db apply "devdbdestroyplan"

# Initialize backend for DEV cluster
terraform -chdir=dev init -reconfigure -backend-config="key=dev/eks-accelerator-vpc.tfstate" \
-backend-config="bucket=$TF_VAR_state_s3_bucket" \
-backend-config="region=$TF_VAR_aws_region" \
-backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

aws eks --region $TF_VAR_aws_region update-kubeconfig --name $TF_VAR_dev_cluster_name

# Destroy the infrastructure changes to deploy EKS DEV cluster and install EKS observability Accelerator
terraform -chdir=dev plan -destroy -var aws_region="${TF_VAR_aws_region}" \
-var managed_grafana_workspace_id="${TF_VAR_managed_grafana_workspace_id}" \
-var managed_prometheus_workspace_id="${TF_VAR_managed_prometheus_workspace_id}" \
-var cluster_name="${TF_VAR_dev_cluster_name}" \
-var vpc_id="${TF_eks_cluster_vpc_id}" \
-var vpc_private_subnets="${TF_eks_cluster_private_subnets}" \
-var grafana_api_key="${AMG_API_KEY}" -out=devdestroyplan

terraform -chdir=dev apply "devdestroyplan"

# Initialize backend for PROD cluster
terraform -chdir=prod init -reconfigure -backend-config="key=prod/eks-accelerator-vpc.tfstate" \
-backend-config="bucket=$TF_VAR_state_s3_bucket" \
-backend-config="region=$TF_VAR_aws_region" \
-backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

aws eks --region $TF_VAR_aws_region update-kubeconfig --name $TF_VAR_prod_cluster_name

# Destroy the infrastructure changes to deploy EKS PROD cluster and deploy observability accelerator
terraform -chdir=prod plan -destroy -var aws_region="${TF_VAR_aws_region}" \
-var managed_grafana_workspace_id="${TF_VAR_managed_grafana_workspace_id}" \
-var managed_prometheus_workspace_id="${TF_VAR_managed_prometheus_workspace_id}" \
-var cluster_name="${TF_VAR_prod_cluster_name}" \
-var vpc_id="${TF_eks_cluster_vpc_id}" \
-var vpc_private_subnets="${TF_eks_cluster_private_subnets}" \
-var grafana_api_key="${AMG_API_KEY}" -out=proddestroyplan

terraform -chdir=prod apply "proddestroyplan"

# Empty the state bucket manually if needed. This is intentionally kept commented to protect the state files
# aws s3 rm s3://$TF_VAR_state_s3_bucket --recursive

# Destroy possible resources that may not be cleaned up by terraform

LOAD_BALANCER_ARN=$(aws elbv2 describe-load-balancers --region $TF_VAR_aws_region --names "modern-engg" --query 'LoadBalancers[*].LoadBalancerArn' --output text) || true

TARGET_GROUP_ARNS=$(aws elbv2 describe-target-groups --region $TF_VAR_aws_region --load-balancer-arn $LOAD_BALANCER_ARN --query 'TargetGroups[*].TargetGroupArn' --output text)

# Split the target group ARNs into an array
read -r -a TARGET_GROUP_ARN_ARRAY <<< "$TARGET_GROUP_ARNS"

# Loop through each target group ARN and delete the target group
for TARGET_GROUP_ARN in "${TARGET_GROUP_ARN_ARRAY[@]}"
do
    echo "Deleting target group: $TARGET_GROUP_ARN"
    aws elbv2 delete-target-group --region $TF_VAR_aws_region --target-group-arn $TARGET_GROUP_ARN || true
done

aws elbv2 delete-load-balancer --region $TF_VAR_aws_region --load-balancer-arn $LOAD_BALANCER_ARN || true

# Destroy bootstrap Bucket, DynamoDB lock table, Amazon Managed Grafana and Amazon Managed Prometheus
#terraform -chdir=bootstrap destroy -auto-approve

# Cleanup the keycloak and AMG Secrets config if not cleaned
aws secretsmanager delete-secret --secret-id "modern-engg/keycloak/config" --force-delete-without-recovery --region $TF_VAR_aws_region || true

aws secretsmanager delete-secret --secret-id "modern-engg/devlake/encryption" --force-delete-without-recovery --region $TF_VAR_aws_region || true

aws secretsmanager delete-secret --secret-id "modern-engg/amg" --force-delete-without-recovery --region $TF_VAR_aws_region || true

aws secretsmanager delete-secret --secret-id "/platform/amp" --force-delete-without-recovery --region $TF_VAR_aws_region || true

aws secretsmanager delete-secret --secret-id "modern-engg-aurora" --force-delete-without-recovery --region $TF_VAR_aws_region || true

aws secretsmanager delete-secret --secret-id "modern-engg-sqlserver" --force-delete-without-recovery --region $TF_VAR_aws_region || true
# Delete the cluster if deletion is not clean

aws eks delete-cluster --name $TF_VAR_dev_cluster_name || true

aws eks delete-cluster --name $TF_VAR_prod_cluster_name || true

# Delete the providers
kubectl delete providers.pkg.crossplane.io provider-aws-apigatewayv2 provider-aws-dynamodb provider-aws-eks provider-aws-iam || true
kubectl delete providers.pkg.crossplane.io provider-aws-lambda provider-aws-rds provider-aws-s3 provider-family-aws || true

# Cleanup the IDP Builder and applications
${REPO_ROOT}/platform/infra/terraform/mgmt/setups/uninstall.sh

# Cleanup the IDP EKS management cluster and prerequisites
${REPO_ROOT}/platform/infra/terraform/mgmt/terraform/mgmt-cluster/uninstall.sh

rm -rf ${REPO_ROOT}/platform/infra/terraform/.git || true

echo "Terraform execution completed"

# Cleanup Folders
rm -rf terraform-aws-observability-accelerator/

echo "Destroy Complete"
