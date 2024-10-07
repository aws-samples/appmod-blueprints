#!/bin/bash
aws eks update-kubeconfig --region $TF_VAR_aws_region --name $TF_VAR_dev_cluster_name

git clone https://github.com/aws-observability/terraform-aws-observability-accelerator.git

# Initialize backend for DEV cluster
terraform -chdir=dev init -reconfigure -backend-config="key=dev/eks-accelerator-vpc.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Apply the infrastructure changes to deploy EKS DEV cluster and install EKS observability Accelerator
terraform -chdir=dev apply -var aws_region="${TF_VAR_aws_region}" \
  -var managed_grafana_workspace_id="${TF_VAR_managed_grafana_workspace_id}" \
  -var managed_prometheus_workspace_id="${TF_VAR_managed_prometheus_workspace_id}" \
  -var cluster_name="${TF_VAR_dev_cluster_name}" \
  -var grafana_api_key="${AMG_API_KEY}" -auto-approve

aws eks update-kubeconfig --region $TF_VAR_aws_region --name $TF_VAR_prod_cluster_name

# Initialize backend for PROD cluster
terraform -chdir=prod init -reconfigure -backend-config="key=prod/eks-accelerator-vpc.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Apply the infrastructure changes to deploy EKS PROD cluster and deploy observability accelerator
terraform -chdir=prod apply -var aws_region="${TF_VAR_aws_region}" \
  -var managed_grafana_workspace_id="${TF_VAR_managed_grafana_workspace_id}" \
  -var managed_prometheus_workspace_id="${TF_VAR_managed_prometheus_workspace_id}" \
  -var cluster_name="${TF_VAR_prod_cluster_name}" \
  -var grafana_api_key="${AMG_API_KEY}" -auto-approve

echo "-------- Dev Cluster --------"
terraform -chdir=dev output

echo "-------- Prod Cluster --------"
terraform -chdir=prod output

echo "Terraform execution completed"

# Cleanup Folders
rm -rf terraform-aws-observability-accelerator/
rm -rf bootstrap/managed-grafana-workspace

echo "Script Complete"
