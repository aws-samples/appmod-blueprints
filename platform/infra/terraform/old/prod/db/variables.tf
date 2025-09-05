variable "aws_region" {
  description = "AWS Region"
  type        = string
  default = "us-west-2"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID of the EKS Cluster"
}

variable "vpc_private_subnets" {
  type        = list(string)
  description = "EKS Private Subnets of the VPC"
}

##### added below for DB and EC2########

variable "vpc_name" {
  description = "Name of the existing VPC (leave empty to create a new VPC)"
  type        = string
  default     = "modern-engineering"
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "ws-prod"
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
  description = "List of availability zones (optional)"
  type        = list(string)
}

variable "key_name" {
  description = "The name of the key pair to use for the EC2 instance"
  type        = string
}
