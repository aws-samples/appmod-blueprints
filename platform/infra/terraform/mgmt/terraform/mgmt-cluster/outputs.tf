output "eks_cluster_vpc_id" {
  description = "EKS Cluster VPC ID"
  value       = module.vpc.vpc_id
}

output "eks_cluster_private_subnets" {
  description = "EKS Cluster VPC Private Subnets"
  value       = module.vpc.private_subnets
}

output "vpc_cidr" {
  description = "Default VPC CIDR of the VPC created by the Module"
  value = local.vpc_cidr
}

output "availability_zones" {
  description = "Default Availability Zone of the VPC created by the Module"
  value = local.azs
}

output "lb_sg" {
  description = "Security Group ID for the lb"
  value = aws_security_group.lb_sg.id
}

output "node_sg" {
  description = "Security Group ID for the Auto Mode Nodes"
  value = aws_security_group.node_sg.id
}