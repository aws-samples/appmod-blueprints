variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.31"
}

variable "addons" {
  description = "EKS addons"
  type        = any
  default = {
    enable_metrics_server               = true
    enable_cw_prometheus                = true
    enable_kyverno                      = true
    enable_kyverno_policy_reporter      = true
    enable_kyverno_policies             = true
  }
}

variable "kms_key_admin_roles" {
  description = "list of role ARNs to add to the KMS policy"
  type        = list(string)
  default     = []

}

variable "resource_prefix" {
  description = "Prefix for project"
  type        = string
  default     = "peeks"
}

variable "ssm_parameter_name_argocd_role_suffix" {
  description = "SSM parameter name for ArgoCD role"
  type        = string
  default     = "argocd-central-role"
}

variable "amazon_managed_prometheus_suffix" {
  description = "SSM parameter name for Amazon Manged Prometheus"
  type        = string
  default     = "amp-hub"
}

variable "ingress_name" {
  description = "Name for the ingress load balancer"
  type        = string
  default     = ""
}

variable "backend_team_view_role_suffix" {
  description = "SSM parameter name for peeks Workshop Team Backend IAM Role"
  type        = string
  default     = "backend-team-view-role"
}
variable "frontend_team_view_role_suffix" {
  description = "SSM parameter name for peeks Workshop Team Backend IAM Role"
  type        = string
  default     = "frontend-team-view-role"
}

variable "enable_prometheus_scraper" {
  description = "Enable Prometheus Scraper"
  type        = bool
  default     = false
}

variable "cluster_name_prefix" {
  description = "Prefix for the EKS spoke cluster name (will be appended with workspace name)"
  type        = string
  default     = "peeks-spoke"
}

# GitOps repository configuration
variable "git_hostname" {
  description = "Git hostname"
  type        = string
  default     = ""
}

variable "git_org_name" {
  description = "Git organization name"
  type        = string
  default     = "user1"
}

variable "gitops_addons_repo_name" {
  description = "GitOps addons repository name"
  type        = string
  default     = "platform-on-eks-workshop"
}

variable "gitops_addons_repo_path" {
  description = "GitOps addons repository path"
  type        = string
  default     = "bootstrap"
}

variable "gitops_addons_repo_base_path" {
  description = "GitOps addons repository base path"
  type        = string
  default     = "gitops/addons/"
}

variable "gitops_addons_repo_revision" {
  description = "GitOps addons repository revision"
  type        = string
  default     = "main"
}

variable "gitops_fleet_repo_name" {
  description = "GitOps fleet repository name"
  type        = string
  default     = "platform-on-eks-workshop"
}

variable "gitops_fleet_repo_path" {
  description = "GitOps fleet repository path"
  type        = string
  default     = "bootstrap"
}

variable "gitops_fleet_repo_base_path" {
  description = "GitOps fleet repository base path"
  type        = string
  default     = "gitops/fleet/"
}

variable "gitops_fleet_repo_revision" {
  description = "GitOps fleet repository revision"
  type        = string
  default     = "main"
}

variable "gitops_workload_repo_name" {
  description = "GitOps workload repository name"
  type        = string
  default     = "platform-on-eks-workshop"
}

variable "gitops_workload_repo_path" {
  description = "GitOps workload repository path"
  type        = string
  default     = ""
}

variable "gitops_workload_repo_base_path" {
  description = "GitOps workload repository base path"
  type        = string
  default     = "gitops/workloads/"
}

variable "gitops_workload_repo_revision" {
  description = "GitOps workload repository revision"
  type        = string
  default     = "main"
}

variable "gitops_platform_repo_name" {
  description = "GitOps platform repository name"
  type        = string
  default     = "platform-on-eks-workshop"
}

variable "gitops_platform_repo_path" {
  description = "GitOps platform repository path"
  type        = string
  default     = ""
}

variable "gitops_platform_repo_base_path" {
  description = "GitOps platform repository base path"
  type        = string
  default     = "gitops/platform/"
}

variable "gitops_platform_repo_revision" {
  description = "GitOps platform repository revision"
  type        = string
  default     = "main"
}

# Removed gitlab_domain_name variable - use git_hostname instead
