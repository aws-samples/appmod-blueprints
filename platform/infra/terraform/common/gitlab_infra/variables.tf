variable "resource_prefix" {
  description = "Prefix for project"
  type        = string
  default     = "peeks"
}

variable "git_password" {
  description = "Password to login on the Gitea instance"
  type        = string
  sensitive   = true
  default     = ""
}

variable "git_username" {
  description = "Git username for workshop"
  type        = string
  default     = "user1"
}

variable "working_repo" {
  description = "Working repository name"
  type        = string
  default     = "platform-on-eks-workshop"
}

variable "domain_name" {
  description = "Domain name"
  type        = string
  default     = "cnoe.io"
}

variable "repo" {
  description = "Repository configuration"
  type = object({
    url      = string
    revision = string
    path= string
    basepath = string
  })
  default = {
    url      = "https://github.com/aws-samples/appmod-blueprints"
    revision = "main"
    path = "bootstrap"
    basepath = "gitops/fleet/"
  }
}

variable "clusters" {
  description = "Cluster configuration"
  type = object({
    hub = object({
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
    spoke1 = object({
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
        enable_prometheus_scraper        = bool
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
    spoke2 = object({
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
        enable_prometheus_scraper        = bool
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
    hub = {
      name = "cnoe-ref-impl"
      region = "us-west-2"
      auto_mode = true
      environment = "control-plane"
      addons = {
        enable_argocd                    = false
        enable_ack_iam                   = true
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
    spoke1 = {
      name = "spoke1"
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
        enable_prometheus_scraper        = false
        enable_cw_prometheus             = false
        enable_kro_eks_rgs               = false
        enable_mutli_acct                = false
        enable_ingress_class_alb         = false
        enable_argo_rollouts             = false
        enable_ingress_nginx             = false
        enable_gitlab                    = false
        enable_keycloak                  = false
        enable_argo_workflows            = false
        enable_kargo                     = false
        enable_backstage                 = false
      }
    }
    spoke2 = {
      name = "spoke2"
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
        enable_prometheus_scraper        = false
        enable_cw_prometheus             = false
        enable_kro_eks_rgs               = false
        enable_mutli_acct                = false
        enable_ingress_class_alb         = false
        enable_argo_rollouts             = false
        enable_ingress_nginx             = false
        enable_gitlab                    = false
        enable_keycloak                  = false
        enable_argo_workflows            = false
        enable_kargo                     = false
        enable_backstage                 = false
      }
    }
  }
}
