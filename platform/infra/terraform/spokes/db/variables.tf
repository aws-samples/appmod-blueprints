variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID of the EKS Cluster"
}

variable "vpc_private_subnets" {
  type        = list(string)
  description = "EKS Private Subnets of the VPC"
}

variable "cluster_name_prefix" {
  description = "Prefix for cluster names"
  type        = string
  default     = "peeks"
}

variable "db_username" {
  description = "Username for the database"
  type        = string
  sensitive   = true
  default     = "postgres"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
}

variable "key_name" {
  description = "The name of the key pair to use for the EC2 instance"
  type        = string
  default     = "ws-default-keypair"
}
