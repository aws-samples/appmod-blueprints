variable "aws_region" {
  description = "AWS Region"
  type        = string
}

variable "mngmt_cluster_gitea_url" {
  description = "URL of gitea instance in management cluster"
  type        = string
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
