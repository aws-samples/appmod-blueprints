variable "repo_url" {
  description = "Repository URL where application definitions are stored"
  default     = "https://github.com/manabuOrg/ref-impl"
  type        = string
}

variable "repo_branch" {
  description = "Repository Branch where application definitions are stored"
  default     = "main"
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

variable "domain_name" {
  description = "if external DNS is not used, this value must be provided."
  default     = "svc.cluster.local"
  type        = string
}

variable "organization_url" {
  description = "github organization url"
  default     = "https://github.com/aws-samples"
  type        = string
}

variable "enable_terraform_integrations" {
  description = "Do you want to apply the flux and tofu-controller manifests to create terraform resources in backstage?"
  default     = false
  type        = bool
}

variable "enable_external_secret" {
  description = "Do you want to use external secret to manage dns records in Route53?"
  default     = true
  type        = bool
}

variable "enable_aiml_integrations" {
  description = "Do you want to apply the spark and ray operator manifests to create ai/ml in backstage?"
  default     = false
  type        = bool
}