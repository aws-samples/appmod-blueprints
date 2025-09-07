data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  # Do not include local zones
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}
data "aws_iam_session_context" "current" {
  # This data source provides information on the IAM source role of an STS assumed role
  # For non-role ARNs, this data source simply passes the ARN through issuer ARN
  # Ref https://github.com/terraform-aws-modules/terraform-aws-eks/issues/2327#issuecomment-1355581682
  # Ref https://github.com/hashicorp/terraform-provider-aws/issues/28381
  arn = data.aws_caller_identity.current.arn
}

# Reading parameter created by hub cluster to allow access of argocd to spoke clusters
data "aws_ssm_parameter" "argocd_hub_role" {
  name = "${local.context_prefix}-${var.ssm_parameter_name_argocd_role_suffix}"
}

# Reading parameter created by common terraform module for team backend and frontend IAM roles
data "aws_ssm_parameter" "backend_team_view_role" {
  name  = "${local.context_prefix}-${var.backend_team_view_role_suffix}"
}
data "aws_ssm_parameter" "frontend_team_view_role" {
  name  = "${local.context_prefix}-${var.frontend_team_view_role_suffix}"
}


locals {
  context_prefix = var.project_context_prefix
  name            = "${var.cluster_name_prefix}-${terraform.workspace}"
  region          = data.aws_region.current.id
  cluster_version = var.kubernetes_version
  vpc_cidr        = var.vpc_cidr
  azs             = slice(data.aws_availability_zones.available.names, 0, 2)
  argocd_namespace    = "argocd"
  adot_collector_namespace = "adot-collector-kubeprometheus"
  adot_collector_service_account = "adot-collector-kubeprometheus"
  ingress_security_groups = "${aws_security_group.ingress_http.id},${aws_security_group.ingress_https.id}"

  # GitOps repository URLs
  git_hostname = var.git_hostname == "" ? "d1vvjck0a1cre3.cloudfront.net" : var.git_hostname
  gitops_addons_repo_url = "https://${local.git_hostname}/${var.git_org_name}/${var.gitops_addons_repo_name}.git"
  gitops_fleet_repo_url = "https://${local.git_hostname}/${var.git_org_name}/${var.gitops_fleet_repo_name}.git"
  gitops_workload_repo_url = "https://${local.git_hostname}/${var.git_org_name}/${var.gitops_workload_repo_name}.git"
  gitops_platform_repo_url = "https://${local.git_hostname}/${var.git_org_name}/${var.gitops_platform_repo_name}.git"

  external_secrets = {
    namespace             = "external-secrets"
    service_account       = "external-secrets-sa"
    namespace_fleet       = "argocd"
  }
  aws_load_balancer_controller = {
    namespace       = "kube-system"
    service_account = "aws-load-balancer-controller-sa"
  }


  aws_addons = {
    enable_cert_manager                          = try(var.addons.enable_cert_manager, false)
    enable_aws_efs_csi_driver                    = try(var.addons.enable_aws_efs_csi_driver, false)
    enable_aws_fsx_csi_driver                    = try(var.addons.enable_aws_fsx_csi_driver, false)
    enable_aws_cloudwatch_metrics                = try(var.addons.enable_aws_cloudwatch_metrics, false)
    enable_aws_privateca_issuer                  = try(var.addons.enable_aws_privateca_issuer, false)
    enable_cluster_autoscaler                    = try(var.addons.enable_cluster_autoscaler, false)
    enable_external_dns                          = try(var.addons.enable_external_dns, false)
    enable_external_secrets                      = try(var.addons.enable_external_secrets, false)
    enable_aws_load_balancer_controller          = try(var.addons.enable_aws_load_balancer_controller, false)
    enable_fargate_fluentbit                     = try(var.addons.enable_fargate_fluentbit, false)
    enable_aws_for_fluentbit                     = try(var.addons.enable_aws_for_fluentbit, false)
    enable_aws_node_termination_handler          = try(var.addons.enable_aws_node_termination_handler, false)
    enable_karpenter                             = try(var.addons.enable_karpenter, false)
    enable_velero                                = try(var.addons.enable_velero, false)
    enable_aws_gateway_api_controller            = try(var.addons.enable_aws_gateway_api_controller, false)
    enable_aws_ebs_csi_resources                 = try(var.addons.enable_aws_ebs_csi_resources, false)
    enable_aws_secrets_store_csi_driver_provider = try(var.addons.enable_aws_secrets_store_csi_driver_provider, false)
    enable_ack_apigatewayv2                      = try(var.addons.enable_ack_apigatewayv2, false)
    enable_ack_dynamodb                          = try(var.addons.enable_ack_dynamodb, false)
    enable_ack_s3                                = try(var.addons.enable_ack_s3, false)
    enable_ack_rds                               = try(var.addons.enable_ack_rds, false)
    enable_ack_prometheusservice                 = try(var.addons.enable_ack_prometheusservice, false)
    enable_ack_emrcontainers                     = try(var.addons.enable_ack_emrcontainers, false)
    enable_ack_sfn                               = try(var.addons.enable_ack_sfn, false)
    enable_ack_eventbridge                       = try(var.addons.enable_ack_eventbridge, false)
    enable_aws_argocd                            = try(var.addons.enable_aws_argocd , false)
    enable_cw_prometheus                         = try(var.addons.enable_cw_prometheus, false)
    enable_cni_metrics_helper                    = try(var.addons.enable_cni_metrics_helper, false)

  }
  oss_addons = {
    enable_argocd                          = try(var.addons.enable_argocd, false)
    enable_argo_rollouts                   = try(var.addons.enable_argo_rollouts, false)
    enable_argo_events                     = try(var.addons.enable_argo_events, false)
    enable_argo_workflows                  = try(var.addons.enable_argo_workflows, false)
    enable_cluster_proportional_autoscaler = try(var.addons.enable_cluster_proportional_autoscaler, false)
    enable_gatekeeper                      = try(var.addons.enable_gatekeeper, false)
    enable_gpu_operator                    = try(var.addons.enable_gpu_operator, false)
    enable_ingress_nginx                   = try(var.addons.enable_ingress_nginx, false)
    enable_keda                            = try(var.addons.enable_keda, false)
    enable_kyverno                         = try(var.addons.enable_kyverno, false)
    enable_kyverno_policy_reporter         = try(var.addons.enable_kyverno_policy_reporter, false)
    enable_kyverno_policies                = try(var.addons.enable_kyverno_policies, false)
    enable_kube_prometheus_stack           = try(var.addons.enable_kube_prometheus_stack, false)
    enable_metrics_server                  = try(var.addons.enable_metrics_server, false)
    enable_prometheus_adapter              = try(var.addons.enable_prometheus_adapter, false)
    enable_secrets_store_csi_driver        = try(var.addons.enable_secrets_store_csi_driver, false)
    enable_vpa                             = try(var.addons.enable_vpa, false)
  }
  addons = merge(
    #
    # GitOps bridge does not use enable_XXXXX labels on the cluster secret in argocd.
    # Labels are removed to avoid confusion
    #
    #local.aws_addons,
    #local.oss_addons,
    { kubernetes_version = local.cluster_version },
    { aws_cluster_name = module.eks.cluster_name },
    { install_argocd = "true" },
  )

  addons_metadata = merge(
    module.eks_blueprints_addons.gitops_metadata,
    {
      aws_cluster_name = module.eks.cluster_name
      aws_region       = local.region
      aws_account_id   = data.aws_caller_identity.current.account_id
      aws_vpc_id       = module.vpc.vpc_id
    },
    {
      external_secrets_namespace = local.external_secrets.namespace
      external_secrets_service_account = local.external_secrets.service_account
      external_secrets_namespace_fleet = local.external_secrets.namespace_fleet # is this used ?
      external_secrets_service_account_fleet = local.external_secrets.service_account # is this used ?
    },
    {
      aws_load_balancer_controller_namespace = local.aws_load_balancer_controller.namespace
      aws_load_balancer_controller_service_account = local.aws_load_balancer_controller.service_account
    },
    {
      # Opensource monitoring
      amp_endpoint_url = "${data.aws_ssm_parameter.amp_endpoint.value}"
      adot_collector_namespace = local.adot_collector_namespace
      adot_collector_service_account = local.adot_collector_service_account
    },
    {
      # GitOps repository configuration
      addons_repo_url = local.gitops_addons_repo_url
      addons_repo_path = var.gitops_addons_repo_path
      addons_repo_basepath = var.gitops_addons_repo_base_path
      addons_repo_revision = var.gitops_addons_repo_revision
      fleet_repo_url = local.gitops_fleet_repo_url
      fleet_repo_path = var.gitops_fleet_repo_path
      fleet_repo_basepath = var.gitops_fleet_repo_base_path
      fleet_repo_revision = var.gitops_fleet_repo_revision
      workload_repo_url = local.gitops_workload_repo_url
      workload_repo_path = var.gitops_workload_repo_path
      workload_repo_basepath = var.gitops_workload_repo_base_path
      workload_repo_revision = var.gitops_workload_repo_revision
      platform_repo_url = local.gitops_platform_repo_url
      platform_repo_path = var.gitops_platform_repo_path
      platform_repo_basepath = var.gitops_platform_repo_base_path
      platform_repo_revision = var.gitops_platform_repo_revision
    },
    {
      # ArgoCD configuration
      argocd_namespace = local.argocd_namespace
      create_argocd_namespace = "false"
    },
    {
      # Domain configuration
      gitlab_domain_name = var.gitlab_domain_name == "" ? local.git_hostname : var.gitlab_domain_name
    },
    {
      # Git configuration
      git_username = var.git_org_name
      working_repo = var.gitops_addons_repo_name
      use_ack = "true"
    },
    {
      ingress_security_groups = local.ingress_security_groups
      ingress_name = var.ingress_name
    },
    #try(local.external_dns_addons_metadata, {})  # Will default to empty map if not defined
    #can(local.external_dns_addons_metadata) ? local.external_dns_addons_metadata : {}  # Will default to empty map if not defined
  )

  tags = {
    Blueprint  = local.name
    GithubRepo = "github.com/gitops-bridge-dev/gitops-bridge"
  }
}

data "aws_ssm_parameter" "amp_endpoint" {
  name = "${local.context_prefix}-${var.amazon_managed_prometheus_suffix}-endpoint"
}

resource "aws_secretsmanager_secret" "spoke_cluster_secret" {
  name                    = "peeks-hub-cluster/${var.cluster_name_prefix}-${terraform.workspace}"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "argocd_cluster_secret_version" {
  secret_id = aws_secretsmanager_secret.spoke_cluster_secret.id
  secret_string = jsonencode({
    metadata     = local.addons_metadata
    addons       = local.addons
    server       = module.eks.cluster_endpoint
    config = {
      tlsClientConfig = {
        insecure = false,
        caData   = module.eks.cluster_certificate_authority_data
      },
      awsAuthConfig = {
        clusterName = module.eks.cluster_name,
        roleARN     = aws_iam_role.spoke.arn
      }
    }
  })
}

################################################################################
# ArgoCD EKS Access
################################################################################
resource "aws_iam_role" "spoke" {
  name_prefix =  "${local.name}-argocd-spoke"
  assume_role_policy = data.aws_iam_policy_document.assume_role_policy.json
}

data "aws_iam_policy_document" "assume_role_policy" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "AWS"
      identifiers = [data.aws_ssm_parameter.argocd_hub_role.value]
    }
  }
}

################################################################################
# EKS Blueprints Addons
################################################################################
module "eks_blueprints_addons" {
  source  = "aws-ia/eks-blueprints-addons/aws"
  version = "~> 1.21.0"

  cluster_name      = module.eks.cluster_name
  cluster_endpoint  = module.eks.cluster_endpoint
  cluster_version   = module.eks.cluster_version
  oidc_provider_arn = module.eks.oidc_provider_arn

  # Using GitOps Bridge
  create_kubernetes_resources = false

  # EKS Blueprints Addons
  enable_cert_manager                 = local.aws_addons.enable_cert_manager
  enable_aws_efs_csi_driver           = local.aws_addons.enable_aws_efs_csi_driver
  enable_aws_fsx_csi_driver           = local.aws_addons.enable_aws_fsx_csi_driver
  enable_aws_cloudwatch_metrics       = local.aws_addons.enable_aws_cloudwatch_metrics
  enable_aws_privateca_issuer         = local.aws_addons.enable_aws_privateca_issuer
  enable_cluster_autoscaler           = local.aws_addons.enable_cluster_autoscaler
  enable_external_dns                 = local.aws_addons.enable_external_dns
  # using pod identity for external secrets we don't need this
  #enable_external_secrets             = local.aws_addons.enable_external_secrets
  # using pod identity for external secrets we don't need this
  #enable_aws_load_balancer_controller = local.aws_addons.enable_aws_load_balancer_controller
  enable_fargate_fluentbit            = local.aws_addons.enable_fargate_fluentbit
  enable_aws_for_fluentbit            = local.aws_addons.enable_aws_for_fluentbit
  enable_aws_node_termination_handler = local.aws_addons.enable_aws_node_termination_handler
  # using pod identity for karpenter we don't need this
  #enable_karpenter                    = local.aws_addons.enable_karpenter
  enable_velero                       = local.aws_addons.enable_velero
  enable_aws_gateway_api_controller   = local.aws_addons.enable_aws_gateway_api_controller

  tags = local.tags
}

################################################################################
# EKS Cluster
################################################################################
#tfsec:ignore:aws-eks-enable-control-plane-logging
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31.6"

  cluster_name                   = local.name
  cluster_version                = local.cluster_version
  cluster_endpoint_public_access = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  enable_cluster_creator_admin_permissions = true

  cluster_compute_config = {
    enabled    = true
    node_pools = ["general-purpose", "system"]
  }

  access_entries = {
    # This is the role that will be assume by the hub cluster role to access the spoke cluster
    argocd = {
      principal_arn = aws_iam_role.spoke.arn

      policy_associations = {
        argocd = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
    backend_team = {
      user_name = "backend-team"
      kubernetes_groups = ["backend-team-view"]
      principal_arn     = data.aws_ssm_parameter.backend_team_view_role.value
    }
    frontend_team = {
      user_name = "frontend-team"
      kubernetes_groups = ["frontend-team-view"]
      principal_arn     = data.aws_ssm_parameter.frontend_team_view_role.value
    }
  }
  node_security_group_additional_rules = {
      # Allows Control Plane Nodes to talk to Worker nodes vpc cni metrics port
      vpc_cni_metrics_traffic = {
        description                   = "Cluster API to node 61678/tcp vpc cni metrics"
        protocol                      = "tcp"
        from_port                     = 61678
        to_port                       = 61678
        type                          = "ingress"
        source_cluster_security_group = true
      }
    }
  node_security_group_tags = merge(local.tags, {
    # EKS Auto Mode handles node provisioning automatically
  })
  tags = local.tags
}


################################################################################
# Supporting Resources
################################################################################
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = local.name
  cidr = local.vpc_cidr

  azs             = local.azs
  private_subnets = [for k, v in local.azs : cidrsubnet(local.vpc_cidr, 4, k)]
  public_subnets  = [for k, v in local.azs : cidrsubnet(local.vpc_cidr, 8, k + 48)]

  enable_nat_gateway = true
  single_nat_gateway = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }

  tags = local.tags
}

################################################################################
# ACK Controller Pod Identity Associations
################################################################################

# Get ACK controller IAM roles created by hub cluster
data "aws_iam_role" "ack_controller" {
  for_each = toset(["iam", "ec2", "eks"])
  name     = "${local.context_prefix}-hub-cluster-ack-${each.key}-controller-role-mgmt"
}

# Create pod identity associations for ACK controllers
resource "aws_eks_pod_identity_association" "ack_controller" {
  for_each = toset(["iam", "ec2", "eks"])

  cluster_name    = module.eks.cluster_name
  namespace       = "ack-system"
  service_account = "ack-${each.key}-controller"
  role_arn        = data.aws_iam_role.ack_controller[each.key].arn

  depends_on = [module.eks]
}

