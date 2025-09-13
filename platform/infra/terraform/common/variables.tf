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

variable "git_password" {
  description = "Password to login on the Git instance"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ide_password" {
  description = "IDE password for workshop admin accounts"
  type        = string
  sensitive   = true
}

variable "git_username" {
  description = "Git username for workshop"
  type        = string
  default     = "user1"
}

variable "domain_name" {
  description = "Domain name"
  type        = string
  default     = "cnoe.io"
}

variable "create_github_repos" {
  description = "Create Github repos"
  type        = bool
  default     = false
}

variable "clusters" {
  description = "Cluster configuration"
  type = object({
    mgmt = object({
      name = string
      region = string
      environment = string
      auto_mode = bool
      addons = object({
        enable_argocd                    = bool
        enable_ack_iam                   = bool
        enable_ack_eks                   = bool
        enable_ack_ec2                   = bool
        enable_external_secrets          = bool
        enable_metrics_server            = bool
        enable_kro                       = bool
        enable_ack_efs                   = bool
        enable_aws_efs_csi_driver        = bool
        enable_aws_for_fluentbit         = bool
        enable_cert_manager              = bool
        enable_external_dns              = bool
        enable_opentelemetry_operator    = bool
        enable_kyverno                   = bool
        enable_kyverno_policy_reporter   = bool
        enable_kyverno_policies          = bool
        enable_cni_metrics_helper        = bool
        enable_kube_state_metrics        = bool
        enable_prometheus_node_exporter  = bool
        enable_cw_prometheus             = bool
        enable_kro_eks_rgs               = bool
        enable_mutli_acct                = bool
        enable_ingress_class_alb         = bool
        enable_argo_rollouts             = bool
        enable_ingress_nginx             = bool
        enable_gitlab                    = bool
        enable_keycloak                  = bool
        enable_argo_workflows            = bool
        enable_kargo                     = bool
        enable_backstage                 = bool
      })
    })
  })
  default = {
    mgmt = {
      name = "cnoe-ref-impl"
      region = "us-west-2"
      auto_mode = true
      environment = "control-plane"
      addons = {
        enable_argocd                    = false
        enable_ack_iam                   = false
        enable_ack_eks                   = false
        enable_ack_ec2                   = false
        enable_external_secrets          = false
        enable_metrics_server            = false
        enable_kro                       = false
        enable_ack_efs                   = false
        enable_aws_efs_csi_driver        = false
        enable_aws_for_fluentbit         = false
        enable_cert_manager              = false
        enable_external_dns              = false
        enable_opentelemetry_operator    = false
        enable_kyverno                   = false
        enable_kyverno_policy_reporter   = false
        enable_kyverno_policies          = false
        enable_cni_metrics_helper        = false
        enable_kube_state_metrics        = false
        enable_prometheus_node_exporter  = false
        enable_cw_prometheus             = false
        enable_kro_eks_rgs               = false
        enable_mutli_acct                = false
        enable_ingress_class_alb         = false
        enable_argo_rollouts             = false
        enable_ingress_nginx             = false
        enable_gitlab                    = true
        enable_keycloak                  = false
        enable_argo_workflows            = false
        enable_kargo                     = false
        enable_backstage                 = false
      }
    }
  }
}

variable "tenant" {
  description = "Name of the tenant for the Hub Cluster"
  type        = string
  default     = "control-plane"
}
variable "gitops_addons_repo_name" {
  description = "The name of git repo"
  default     = "kro"
}

variable "gitops_addons_repo_path" {
  description = "The path of addons bootstraps in the repo"
  default     = "bootstrap"
}

variable "gitops_addons_repo_base_path" {
  description = "The base path of addons in the repon"
  default     = "gitops/addons/"
}

variable "gitops_addons_repo_revision" {
  description = "The name of branch or tag"
  default     = "main"
}
# Fleet
variable "gitops_fleet_repo_name" {
  description = "The name of Git repo"
  default     = "kro"
}

variable "gitops_fleet_repo_path" {
  description = "The path of fleet bootstraps in the repo"
  default     = "bootstrap"
}

variable "gitops_fleet_repo_base_path" {
  description = "The base path of fleet in the repon"
  default     = "examples/aws/eks-cluster-mgmt/fleet/"
}

variable "gitops_fleet_repo_revision" {
  description = "The name of branch or tag"
  default     = "main"
}

# workload
variable "gitops_workload_repo_name" {
  description = "The name of Git repo"
  default     = "kro"
}

variable "gitops_workload_repo_path" {
  description = "The path of workload bootstraps in the repo"
  default     = "examples/aws/eks-cluster-mgmt/apps/"
}

variable "gitops_workload_repo_base_path" {
  description = "The base path of workloads in the repo"
  default     = ""
}

variable "gitops_workload_repo_revision" {
  description = "The name of branch or tag"
  default     = "main"
}

# Platform
variable "gitops_platform_repo_name" {
  description = "The name of Git repo"
  default     = "kro"
}

variable "gitops_platform_repo_path" {
  description = "The path of platform bootstraps in the repo"
  default     = "bootstrap"
}

variable "gitops_platform_repo_base_path" {
  description = "The base path of platform in the repo"
  default     = "examples/aws/eks-cluster-mgmt/platform/"
}

variable "gitops_platform_repo_revision" {
  description = "The name of branch or tag"
  default     = "main"
}
# variable "secret_name_ssh_secrets" {
#   description = "Secret name for SSH secrets"
#   type        = string
#   default     = "peeks-git-ssh-secrets"
# }


# # Removed unused gitops repository variables and gitea_external_url

# variable "ssm_parameter_name_argocd_role_suffix" {
#   description = "SSM parameter name for ArgoCD role"
#   type        = string
#   default     = "argocd-central-role"
# }
# variable "amazon_managed_prometheus_suffix" {
#   description = "SSM parameter name for Amazon Manged Prometheus"
#   type        = string
#   default     = "amp-hub"
# }
# variable "backend_team_view_role_suffix" {
#   description = "SSM parameter name for peeks Workshop Team Backend IAM Role"
#   type        = string
#   default     = "backend-team-view-role"
# }
# variable "frontend_team_view_role_suffix" {
#   description = "SSM parameter name for peeks Workshop Team Backend IAM Role"
#   type        = string
#   default     = "frontend-team-view-role"
# }

# variable "gitea_user" {
#   description = "User to login on the Gitea instance"
#   type = string
#   default = "user1"
# }
# variable "git_password" {
#   description = "Password to login on the Gitea instance"
#   type = string
#   sensitive = true
#   default = ""
# }

# variable "ide_password" {
#   description = "IDE password for workshop admin accounts"
#   type        = string
#   sensitive   = true
# }

# variable "git_username" {
#   description = "Git username for workshop"
#   type        = string
#   default     = "user1"
# }

# variable "working_repo" {
#   description = "Working repository name"
#   type        = string
#   default     = "platform-on-eks-workshop"
# }

# # Removed unused gitea_external_url and gitea_repo_prefix variables

# variable "create_github_repos" {
#   description = "Create Github repos"
#   type = bool
#   default = false
# }