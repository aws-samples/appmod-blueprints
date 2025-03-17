terraform {
  required_version = ">= 1.3.0"

  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0.0"
    }
    kubectl = {
      source  = "alekc/kubectl"
      version = ">= 2.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  tags = {
    Blueprint  = var.cluster_name
    GithubRepo = "github.com/aws-observability/terraform-aws-observability-accelerator"
  }
}

#---------------------------------------------------------------
# EKS Blueprints
#---------------------------------------------------------------

module "eks_blueprints_prod" {
  source = "github.com/aws-ia/terraform-aws-eks-blueprints?ref=v4.32.1"

  cluster_name    = var.cluster_name
  cluster_version = var.eks_version

  vpc_id             = var.vpc_id
  private_subnet_ids = var.vpc_private_subnets

  managed_node_groups = {
    mg_5 = {
      node_group_name = "managed-ondemand"
      instance_types  = [var.managed_node_instance_type]
      min_size        = var.managed_node_min_size
      subnet_ids      = var.vpc_private_subnets
    }
  }

  tags = local.tags
}

module "eks_blueprints_kubernetes_addons" {
  source = "github.com/aws-ia/terraform-aws-eks-blueprints//modules/kubernetes-addons?ref=v4.32.1"

  eks_cluster_id       = module.eks_blueprints_prod.eks_cluster_id
  eks_cluster_endpoint = module.eks_blueprints_prod.eks_cluster_endpoint
  eks_oidc_provider    = module.eks_blueprints_prod.oidc_provider
  eks_cluster_version  = module.eks_blueprints_prod.eks_cluster_version

  # EKS Managed Add-ons
  enable_amazon_eks_vpc_cni            = true
  enable_amazon_eks_coredns            = true
  enable_amazon_eks_kube_proxy         = true
  enable_amazon_eks_aws_ebs_csi_driver = true
  enable_crossplane                    = false

  tags = local.tags
}

module "eks_blueprints_addons_prod" {
  source = "aws-ia/eks-blueprints-addons/aws"
  version = "~> 1.16.3" #ensure to update this to the latest/desired version

  cluster_name      = module.eks_blueprints_prod.eks_cluster_id
  cluster_endpoint  = module.eks_blueprints_prod.eks_cluster_endpoint
  cluster_version   = module.eks_blueprints_prod.eks_cluster_version
  oidc_provider_arn = module.eks_blueprints_prod.eks_oidc_provider_arn

  eks_addons = {
    eks-pod-identity-agent = {
      most_recent = true
    }
  }

  tags = local.tags
}

# module "eks_prod_cluster_with_vpc" {
#   source  = "../terraform-aws-observability-accelerator/examples/eks-cluster-with-vpc"
#   aws_region = var.aws_region
#   cluster_name = var.cluster_name
# }

# module "eks_prod_observability_accelerator" {
#   source  = "../terraform-aws-observability-accelerator/examples/existing-cluster-with-base-and-infra"
#   eks_cluster_id = module.eks_prod_cluster_with_vpc.eks_cluster_id
#   aws_region = var.aws_region
#   managed_grafana_workspace_id = var.managed_grafana_workspace_id
#   managed_prometheus_workspace_id = var.managed_prometheus_workspace_id
#   grafana_api_key = var.grafana_api_key
# }

module "eks_prod_monitoring" {
  source                  = "../terraform-aws-observability-accelerator/modules/eks-monitoring"
  eks_cluster_id          = module.eks_blueprints_prod.eks_cluster_id
  enable_amazon_eks_adot  = true
  enable_cert_manager     = true
  enable_java             = true
  enable_nginx            = true
  enable_custom_metrics   = true
  enable_external_secrets = true
  enable_fluxcd           = true

  # Since the following were enabled in conjunction with the set up of the
  # eks_cluster_1 EKS cluster, we will skip them with the eks_cluster_2 EKS cluster
  enable_dashboards       = false
  enable_alerting_rules   = false
  enable_recording_rules  = false

  # Disable additional dashboards
  enable_apiserver_monitoring  = false
  enable_adotcollector_metrics = false
  enable_nvidia_monitoring     = false

  # grafana_api_key = var.grafana_api_key
  # grafana_url     = "https://${data.aws_grafana_workspace.prod_amg_ws.endpoint}"

  # prevents the module to create a workspace
  enable_managed_prometheus = false

  managed_prometheus_workspace_id       = var.managed_prometheus_workspace_id
  managed_prometheus_workspace_endpoint = data.aws_prometheus_workspace.prod_amp_ws.prometheus_endpoint
  managed_prometheus_workspace_region   = var.aws_region

  prometheus_config = {
    global_scrape_interval = "60s"
    global_scrape_timeout  = "15s"
    scrape_sample_limit    = 2000
  }

  custom_metrics_config = {
    polyglot_app_config = {
        enableBasicAuth       = false
        path                  = "/metrics"
        basicAuthUsername     = "username"
        basicAuthPassword     = "password"
        ports                 = ".*:(8080)$"
        droppedSeriesPrefixes = "(unspecified.*)$"
    }
  }
}

data "aws_grafana_workspace" "prod_amg_ws" {
  workspace_id = var.managed_grafana_workspace_id
}

data "aws_prometheus_workspace" "prod_amp_ws" {
  workspace_id = var.managed_prometheus_workspace_id
}

data "aws_eks_cluster_auth" "prod_cluster_auth" {
  name = module.eks_blueprints_prod.eks_cluster_id
}

data "aws_eks_cluster" "prod_cluster_name" {
  name = module.eks_blueprints_prod.eks_cluster_id
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.prod_cluster_name.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.prod_cluster_name.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.prod_cluster_auth.token
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.prod_cluster_name.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.prod_cluster_name.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.prod_cluster_auth.token
  }
}

provider "kubectl" {
  host                   = data.aws_eks_cluster.prod_cluster_name.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.prod_cluster_name.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.prod_cluster_auth.token
  load_config_file       = false
}

# Setup GitOps management for access from Management Cluster
resource "kubernetes_service_account_v1" "prod_argocd_auth_manager" {
  metadata {
    name      = "prod-argocd-manager"
    namespace = "kube-system"
  }
}

resource "kubernetes_secret_v1" "prod_argocd_secret" {
  metadata {
    name      = "prod-argocd-manager-token"
    namespace = "kube-system"
    annotations = {
      "kubernetes.io/service-account.name" = "${kubernetes_service_account_v1.prod_argocd_auth_manager.metadata.0.name}"
    }
  }
  type = "kubernetes.io/service-account-token"
}

resource "kubernetes_cluster_role_v1" "prod_argocd_gitops" {
  metadata {
    name = "prod-argocd-manager-role"
  }
  rule {
    api_groups = ["*"]
    resources  = ["*"]
    verbs      = ["*"]
  }
}

resource "kubernetes_cluster_role_binding_v1" "prod_argocd_gitops" {
  metadata {
    name = "prod-argocd-manager-role-binding"
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "prod-argocd-manager-role"
  }
  subject {
    kind      = "ServiceAccount"
    name      = "prod-argocd-manager"
    namespace = "kube-system"
  }
}

//Get the secrets created from the serviceaccount
data "kubernetes_secret_v1" "prod_argocd_secret" {
  metadata {
    name  = kubernetes_secret_v1.prod_argocd_secret.metadata.0.name
    namespace = "kube-system"
  }
}

resource "aws_ssm_parameter" "gitops_prod_argocd_authN" {
  name      = "/gitops/prod-argocd-token"
  value     = data.kubernetes_secret_v1.prod_argocd_secret.data["token"]
  type      = "SecureString"
}

resource "aws_ssm_parameter" "gitops_prod_argocd_authCA" {
  name      = "/gitops/prod-argocdca"
  value     = data.kubernetes_secret_v1.prod_argocd_secret.data["ca.crt"]
  type      = "SecureString"
}

resource "aws_ssm_parameter" "gitops_prod_argocd_serverurl" {
  name      = "/gitops/prod-serverurl"
  value     = data.aws_eks_cluster.prod_cluster_name.endpoint
  type      = "SecureString"
}

module "crossplane_prod_provider_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.14"

  role_name_prefix = "modernengg-prod-aws"
  role_policy_arns = {
    policy = "arn:aws:iam::aws:policy/AdministratorAccess"
  }

  assume_role_condition_test = "StringLike"
  oidc_providers = {
    main = {
      provider_arn  = module.eks_blueprints_prod.eks_oidc_provider_arn
      namespace_service_accounts = ["crossplane-system:provider-aws*"]
    }
  }
  tags = local.tags
}

module "aws_load_balancer_prod_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.14"

  role_name_prefix = "modern-prod-lb-controller-"

  attach_load_balancer_controller_policy = true

  oidc_providers = {
    main = {
      provider_arn = module.eks_blueprints_prod.eks_oidc_provider_arn
      namespace_service_accounts = ["aws-load-balancer-controller:aws-load-balancer-controller"]
    }
  }
  tags = local.tags
}

module "argo_rollouts_prod_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.14"

  role_name_prefix = "argorollout-prod-aws"
  role_policy_arns = {
    policy = "arn:aws:iam::aws:policy/AmazonPrometheusQueryAccess"
  }

  assume_role_condition_test = "StringLike"
  oidc_providers = {
    main = {
      provider_arn  = module.eks_blueprints_prod.eks_oidc_provider_arn
      namespace_service_accounts = ["argo-rollouts:argo-rollouts*"]
    }
  }
  tags = local.tags
}

module "ack_prod_controller_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.14"

  role_name_prefix = "ack-prod-aws"
  role_policy_arns = {
    policy = "arn:aws:iam::aws:policy/AdministratorAccess"
  }

  assume_role_condition_test = "StringLike"
  oidc_providers = {
    main = {
      provider_arn  = module.eks_blueprints_prod.eks_oidc_provider_arn
      namespace_service_accounts = ["ack-system:controller-ack*"]
    }
  }
  tags = local.tags
}
