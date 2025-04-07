output "eks_cluster_vpc_id" {
  description = "EKS Cluster VPC ID"
  value       = module.vpc.vpc_id
}

output "eks_cluster_private_subnets" {
  description = "EKS Cluster VPC Private Subnets"
  value       = module.vpc.private_subnets
}

output "eks_cluster_node_security_group_id" {
  description = "EKS Cluster Node Security Group Id"
  value = module.eks.node_security_group_id
}

output "vpc_cidr" {
  description = "Default VPC CIDR of the VPC created by the Module"
  value = local.vpc_cidr
}

output "database_subnet_ids" {
  description = "VPC Database Subnet Ids"
  value = module.vpc.database_subnets
}

output "availability_zones" {
  description = "Default Availability Zone of the VPC created by the Module"
  value = local.azs
}
