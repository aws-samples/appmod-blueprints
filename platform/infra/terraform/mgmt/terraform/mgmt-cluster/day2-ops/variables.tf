variable "repo_url" {
  description = "Repository URL where application definitions are stored"
  default     = "https://github.com/elamaran11/cnoe-appmod-implementation"
  type        = string
}

variable "tags" {
  description = "Tags to apply to AWS resources"
  default = {
    env     = "dev"
    project = "modern-engg"
  }
  type = map(string)
}

variable "region" {
  description = "Region"
  type        = string
  default     = "us-west-2"
}

variable "cluster_name" {
  description = "EKS Cluster name"
  default     = "modern-engineering"
  type        = string
}

variable "enable_external_secret" {
  description = "Do you want to use external secret to manage dns records in Route53?"
  default     = true
  type        = bool
}
