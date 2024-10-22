#!/bin/bash

# Initialize backend for DEV - Database Cluster Creation
terraform -chdir=database/dev init -reconfigure -backend-config="key=dev/database-cluster.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Apply the infrastructure changes to deploy DEV Database cluster
terraform -chdir=database/dev apply -var key_name="ws-dev-ec2-key" -var vpc_name=$TF_VAR_vpc_name -auto-approve #-var aws_region="${TF_VAR_aws_region}"
  
# Initialize backend for DEV - Database Cluster Creation
terraform -chdir=database/prod init -reconfigure -backend-config="key=prod/database-cluster.tfstate" \
  -backend-config="bucket=$TF_VAR_state_s3_bucket" \
  -backend-config="region=$TF_VAR_aws_region" \
  -backend-config="dynamodb_table=$TF_VAR_state_ddb_lock_table"

# Apply the infrastructure changes to deploy DEV Database cluster
terraform -chdir=database/prod apply -var key_name="ws-prod-ec2-key" -var vpc_name=$TF_VAR_vpc_name -auto-approve #-var aws_region="${TF_VAR_aws_region}"

echo "-------- Dev Cluster --------"
terraform -chdir=database/dev output

echo "-------- Prod Cluster --------"
terraform -chdir=database/prod output

echo "Terraform execution completed"

# Cleanup Folders

echo "Script Complete"
