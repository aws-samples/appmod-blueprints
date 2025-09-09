variable "resource_prefix" {
  description = "Prefix for project"
  type        = string
  default     = "peeks"
}

variable "secret_name_ssh_secrets" {
  description = "Secret name for SSH secrets"
  type        = string
  default     = "peeks-git-ssh-secrets"
}


# Removed unused gitops repository variables and gitea_external_url

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

variable "gitea_user" {
  description = "User to login on the Gitea instance"
  type = string
  default = "user1"
}
variable "git_password" {
  description = "Password to login on the Gitea instance"
  type = string
  sensitive = true
  default = ""
}

# Removed unused gitea_external_url and gitea_repo_prefix variables

variable "create_github_repos" {
  description = "Create Github repos"
  type = bool
  default = false
}
