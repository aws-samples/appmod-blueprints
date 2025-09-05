variable "aws_region" {
  description = "AWS Region"
  type        = string
  default = "us-west-2"
}

variable "mgmt_cluster_gitea_url" {
  description = "URL of gitea instance in management cluster"
  type        = string
  default     = "value"
}

variable "dev_cluster_name" {
  description = "Dev EKS Cluster Name"
  type        = string
  default     = "modernengg-dev"
}

variable "prod_cluster_name" {
  description = "Prod EKS Cluster Name"
  type        = string
  default     = "modernengg-prod"
}

variable "codebuild_project_name" {
  description = "CodeBuild Project Name"
  type        = string
  default     = "modernengg-codebuild"
}

variable "codebuild_project_name_db_ec2" {
  description = "DB CodeBuild Project Name"
  type        = string
  default     = "modernengg-codebuild-ec2-db"
}