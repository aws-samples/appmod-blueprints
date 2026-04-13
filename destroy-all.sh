#!/bin/bash
set -e

export RESOURCE_PREFIX="peeks"
export AWS_REGION="us-east-2"
export USER1_PASSWORD="${USER1_PASSWORD:-ChangeMe123!}"

echo "Getting cluster info..."
export HUB_VPC_ID=$(aws eks describe-cluster --name ${RESOURCE_PREFIX}-hub --region $AWS_REGION --query 'cluster.resourcesVpcConfig.vpcId' --output text 2>/dev/null || echo "vpc-dummy")
export HUB_SUBNET_IDS=$(aws eks describe-cluster --name ${RESOURCE_PREFIX}-hub --region $AWS_REGION --query 'cluster.resourcesVpcConfig.subnetIds' --output json 2>/dev/null || echo '["subnet-dummy"]')

echo "VPC ID: $HUB_VPC_ID"
echo "Subnet IDs: $HUB_SUBNET_IDS"

echo "Destroying common addons..."
cd /Users/shapirov/projects/appmod-blueprints/platform/infra/terraform/common
terraform destroy \
  -var="ide_password=${USER1_PASSWORD}" \
  -var="resource_prefix=${RESOURCE_PREFIX}" \
  -auto-approve || echo "Common destroy failed, continuing..."

echo "Destroying cluster..."
cd /Users/shapirov/projects/appmod-blueprints/platform/infra/terraform/cluster
terraform destroy \
  -var="hub_vpc_id=${HUB_VPC_ID}" \
  -var="hub_subnet_ids=${HUB_SUBNET_IDS}" \
  -var="resource_prefix=${RESOURCE_PREFIX}" \
  -auto-approve || echo "Cluster destroy failed, continuing..."

echo "Destroying VPC..."
cd /Users/shapirov/projects/appmod-blueprints/platform/infra/terraform/vpc
terraform destroy \
  -var="region=${AWS_REGION}" \
  -var="resource_prefix=${RESOURCE_PREFIX}" \
  -auto-approve || echo "VPC destroy failed"

echo "Destruction complete!"
