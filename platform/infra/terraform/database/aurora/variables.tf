variable "cluster_name_prefix" {
  description = "Prefix for cluster names"
  type        = string
}

variable "vpc_id" {
  type        = string
  description = "VPC ID of the EKS Cluster"
}

variable "vpc_private_subnets" {
  type        = list(string)
  description = "VPC SubnetIds of the EKS Cluster"
}
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}
variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "ws-dev"
}

variable "db_username" {
  description = "Username for the database"
  type        = string
  sensitive   = true
  default     = "postgres"
}

variable "availability_zones" {
    description = "List of availability zones"
    type        = list(string)
}
