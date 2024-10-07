output "eks_cluster_vpc_id" {
  description = "EKS Cluster VPC ID"
  value       = module.vpc.vpc_id
}

output "eks_cluster_private_subnets" {
  description = "EKS Cluster VPC Private Subnets"
  value       = module.vpc.private_subnets
}
