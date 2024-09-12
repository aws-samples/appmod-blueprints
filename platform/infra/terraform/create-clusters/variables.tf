variable "aws_region" {
  description = "AWS Region"
  type        = string
}

variable "mgmt_cluster_gitea_url" {
  description = "URL of gitea instance in management cluster"
  type        = string
}

variable "iam_role_name" {
  description = "Name of IAM role with access to dev and prod clusters"
  type        = string
  default     = "modern-engineering-cluster-creation-role"
}

variable "dev_cluster_name" {
  description = "Dev EKS Cluster Name"
  type        = string
  default     = "appmod-dev"
}

variable "prod_cluster_name" {
  description = "Prod EKS Cluster Name"
  type        = string
  default     = "appmod-prod"
}

variable "codebuild_project_name" {
  description = "CodeBuild Project Name"
  type        = string
}
