variable "vpc_name" {
  description = "Name of the existing VPC (leave empty to create a new VPC)"
  type        = string
  default     = "abcde"
}
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones (optional)"
  type        = list(string)
  default     = []
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

variable "aws_region" {
  description = "The AWS region to create resources in"
  type        = string
  default     = "us-east-1"  # You can change this default as needed
}

variable "key_name" {
  description = "The name of the key pair to use for the EC2 instance"
  type        = string
}
