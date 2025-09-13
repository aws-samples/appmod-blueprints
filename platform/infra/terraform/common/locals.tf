locals {

  context_prefix = var.resource_prefix

  tags = {
    Blueprint  = local.context_prefix
    GithubRepo = "github.com/aws-samples/appmod-blueprints"
  }

}

locals {
  azs                       = slice(data.aws_availability_zones.available.names, 0, 2)
  # use_ack                   = var.use_ack
  # enable_efs                = var.enable_efs
  name                      = data.aws_eks_cluster.mgmt.name
  # environment               = var.environment
  fleet_member              = "control-plane"
  tenant                    = var.tenant
  cluster_name              = data.aws_eks_cluster.mgmt.name
  region                    = var.clusters.mgmt.region
  vpc_id                    = data.aws_eks_cluster.mgmt.vpc_config[0].vpc_id
  # cluster_version           = var.kubernetes_version
  argocd_namespace          = "argocd"
  ingress_name              = "${data.aws_eks_cluster.mgmt.name}-ingress"
  ingress_security_groups   = "${aws_security_group.ingress_http.id},${aws_security_group.ingress_https.id}"
  gitlab_security_groups    = "${aws_security_group.gitlab_ssh.id},${aws_security_group.gitlab_http.id}"
  ingress_nlb_domain_name   = "${data.aws_lb.ingress_nginx.dns_name}"
  ingress_domain_name       = aws_cloudfront_distribution.ingress.domain_name
  gitlab_nlb_domain_name    = "${data.aws_lb.gitlab_nlb.dns_name}"
  gitlab_domain_name        = aws_cloudfront_distribution.gitlab.domain_name
  # git_hostname              = var.repo == "" ? "${local.gitlab_domain_name}" : var.git_hostname
  # backstage_image           = var.backstage_image == "" ? "${data.aws_caller_identity.current.account_id}.dkr.ecr.${local.region}.amazonaws.com/${var.resource_prefix}-backstage:latest" : var.backstage_image
  gitops_addons_repo_url    = local.gitlab_domain_name != "" ? "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url
  gitops_fleet_repo_url       = local.gitlab_domain_name != "" ? "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url
  # gitops_fleet_repo_url       = "https://${local.gitlab_domain_name}/${var.git_org_name}/${var.gitops_fleet_repo_name}.git"
  # gitops_workload_repo_url  = "https://${local.git_hostname}/${var.git_org_name}/${var.gitops_workload_repo_name}.git"
  # gitops_platform_repo_url  = "https://${local.git_hostname}/${var.git_org_name}/${var.gitops_platform_repo_name}.git"

  external_secrets = {
    namespace       = "external-secrets"
    service_account = "external-secrets-sa"
  }
  aws_load_balancer_controller = {
    namespace       = "kube-system"
    service_account = "aws-load-balancer-controller-sa"
  }

  karpenter = {
    namespace       = "kube-system"
    service_account = "karpenter"
    role_name       = "karpenter-${terraform.workspace}"
  }

  iam_ack = {
    namespace       = "ack-system"
    service_account = "ack-iam-controller"
  }

  eks_ack = {
    namespace       = "ack-system"
    service_account = "ack-eks-controller"
  }

  ec2_ack = {
    namespace       = "ack-system"
    service_account = "ack-ec2-controller"
  }

  aws_addons = {
    enable_cert_manager                          = try(var.clusters.mgmt.addons.enable_cert_manager, false)
    enable_aws_efs_csi_driver                    = try(var.clusters.mgmt.addons.enable_aws_efs_csi_driver, false)
    enable_aws_fsx_csi_driver                    = try(var.clusters.mgmt.addons.enable_aws_fsx_csi_driver, false)
    enable_aws_cloudwatch_metrics                = try(var.clusters.mgmt.addons.enable_aws_cloudwatch_metrics, false)
    enable_aws_cloudwatch_observability          = try(var.clusters.mgmt.addons.enable_aws_cloudwatch_observability, false)
    enable_aws_privateca_issuer                  = try(var.clusters.mgmt.addons.enable_aws_privateca_issuer, false)
    enable_cluster_autoscaler                    = try(var.clusters.mgmt.addons.enable_cluster_autoscaler, false)
    enable_external_dns                          = try(var.clusters.mgmt.addons.enable_external_dns, false)
    enable_external_secrets                      = try(var.clusters.mgmt.addons.enable_external_secrets, false)
    enable_aws_load_balancer_controller          = try(var.clusters.mgmt.addons.enable_aws_load_balancer_controller, false)
    enable_fargate_fluentbit                     = try(var.clusters.mgmt.addons.enable_fargate_fluentbit, false)
    enable_aws_for_fluentbit                     = try(var.clusters.mgmt.addons.enable_aws_for_fluentbit, false)
    enable_aws_node_termination_handler          = try(var.clusters.mgmt.addons.enable_aws_node_termination_handler, false)
    enable_karpenter                             = try(var.clusters.mgmt.addons.enable_karpenter, false)
    enable_velero                                = try(var.clusters.mgmt.addons.enable_velero, false)
    enable_aws_gateway_api_controller            = try(var.clusters.mgmt.addons.enable_aws_gateway_api_controller, false)
    enable_aws_ebs_csi_resources                 = try(var.clusters.mgmt.addons.enable_aws_ebs_csi_resources, false)
    enable_aws_secrets_store_csi_driver_provider = try(var.clusters.mgmt.addons.enable_aws_secrets_store_csi_driver_provider, false)
    enable_ack_apigatewayv2                      = try(var.clusters.mgmt.addons.enable_ack_apigatewayv2, false)
    enable_ack_dynamodb                          = try(var.clusters.mgmt.addons.enable_ack_dynamodb, false)
    enable_ack_s3                                = try(var.clusters.mgmt.addons.enable_ack_s3, false)
    enable_ack_rds                               = try(var.clusters.mgmt.addons.enable_ack_rds, false)
    enable_ack_prometheusservice                 = try(var.clusters.mgmt.addons.enable_ack_prometheusservice, false)
    enable_ack_emrcontainers                     = try(var.clusters.mgmt.addons.enable_ack_emrcontainers, false)
    enable_ack_sfn                               = try(var.clusters.mgmt.addons.enable_ack_sfn, false)
    enable_ack_eventbridge                       = try(var.clusters.mgmt.addons.enable_ack_eventbridge, false)
    enable_aws_argocd                            = try(var.clusters.mgmt.addons.enable_aws_argocd, false)
    enable_ack_iam                               = try(var.clusters.mgmt.addons.enable_ack_iam, false)
    enable_ack_eks                               = try(var.clusters.mgmt.addons.enable_ack_eks, false)
    enable_cni_metrics_helper                    = try(var.clusters.mgmt.addons.enable_cni_metrics_helper, false)
    enable_ack_ec2                               = try(var.clusters.mgmt.addons.enable_ack_ec2, false)
    enable_ack_efs                               = try(var.clusters.mgmt.addons.enable_ack_efs, false)
    enable_kro                                   = try(var.clusters.mgmt.addons.enable_kro, false)
    enable_kro_eks_rgs                           = try(var.clusters.mgmt.addons.enable_kro_eks_rgs, false)
    enable_mutli_acct                            = try(var.clusters.mgmt.addons.enable_mutli_acct, false)
    enable_ingress_class_alb                     = try(var.clusters.mgmt.addons.enable_ingress_class_alb, false)

  }
  oss_addons = {
    enable_ingress_nginx                   = try(var.clusters.mgmt.addons.enable_ingress_nginx, false)
    enable_argocd                          = try(var.clusters.mgmt.addons.enable_argocd, false)
    enable_backstage                       = try(var.clusters.mgmt.addons.enable_backstage, false)
    enable_kargo                           = try(var.clusters.mgmt.addons.enable_kargo, false)
    enable_keycloak                        = try(var.clusters.mgmt.addons.enable_keycloak, false)
    enable_gitlab                          = try(var.clusters.mgmt.addons.enable_gitlab, false)
    enable_argo_rollouts                   = try(var.clusters.mgmt.addons.enable_argo_rollouts, false)
    enable_argo_events                     = try(var.clusters.mgmt.addons.enable_argo_events, false)
    enable_argo_workflows                  = try(var.clusters.mgmt.addons.enable_argo_workflows, false)
    enable_cluster_proportional_autoscaler = try(var.clusters.mgmt.addons.enable_cluster_proportional_autoscaler, false)
    enable_gatekeeper                      = try(var.clusters.mgmt.addons.enable_gatekeeper, false)
    enable_gpu_operator                    = try(var.clusters.mgmt.addons.enable_gpu_operator, false)
    enable_keda                            = try(var.clusters.mgmt.addons.enable_keda, false)
    enable_kyverno                         = try(var.clusters.mgmt.addons.enable_kyverno, false)
    enable_kube_prometheus_stack           = try(var.clusters.mgmt.addons.enable_kube_prometheus_stack, false)
    enable_metrics_server                  = try(var.clusters.mgmt.addons.enable_metrics_server, false)
    enable_prometheus_adapter              = try(var.clusters.mgmt.addons.enable_prometheus_adapter, false)
    enable_secrets_store_csi_driver        = try(var.clusters.mgmt.addons.enable_secrets_store_csi_driver, false)
    enable_vpa                             = try(var.clusters.mgmt.addons.enable_vpa, false)
  }

  addons = merge(
    local.aws_addons,
    local.oss_addons,
    { aws_cluster_name = local.cluster_name },
    { fleet_member = local.fleet_member },
    { tenant = local.tenant },
  )

  addons_metadata = merge(
    {
      aws_cluster_name = data.aws_eks_cluster.mgmt.name
      aws_region       = local.region
      aws_account_id   = data.aws_caller_identity.current.account_id
      aws_vpc_id       = data.aws_eks_cluster.mgmt.vpc_config[0].vpc_id
      resource_prefix  = var.resource_prefix
    },
    {
      argocd_namespace        = local.argocd_namespace,
      create_argocd_namespace = false,
      # argocd_controller_role_arn = data.aws_ssm_parameter.argocd_hub_role.value
    },
    {
      addons_repo_url      = local.gitops_addons_repo_url
      addons_repo_path     = var.gitops_addons_repo_path
      addons_repo_basepath = var.gitops_addons_repo_base_path
      addons_repo_revision = var.gitops_addons_repo_revision
    },
    # {
    #   workload_repo_url      = local.gitops_workload_repo_url
    #   workload_repo_path     = var.gitops_workload_repo_path
    #   workload_repo_basepath = var.gitops_workload_repo_base_path
    #   workload_repo_revision = var.gitops_workload_repo_revision
    # },
    {
      fleet_repo_url      = local.gitops_fleet_repo_url
      fleet_repo_path     = var.repo.path
      fleet_repo_basepath = var.repo.basepath
      fleet_repo_revision = var.repo.revision
    },
    # {
    #   platform_repo_url      = local.gitops_platform_repo_url
    #   platform_repo_path     = var.gitops_platform_repo_path
    #   platform_repo_basepath = var.gitops_platform_repo_base_path
    #   platform_repo_revision = var.gitops_fleet_repo_revision
    # },
    {
      external_secrets_namespace       = local.external_secrets.namespace
      external_secrets_service_account = local.external_secrets.service_account
    },
    {
      ack_iam_service_account = local.iam_ack.service_account
      ack_iam_namespace       = local.iam_ack.namespace
      ack_eks_service_account = local.eks_ack.service_account
      ack_eks_namespace       = local.eks_ack.namespace
      ack_ec2_service_account = local.ec2_ack.service_account
      ack_ec2_namespace       = local.ec2_ack.namespace
    },
    {
      aws_load_balancer_controller_namespace       = local.aws_load_balancer_controller.namespace
      aws_load_balancer_controller_service_account = local.aws_load_balancer_controller.service_account
    },
    {
      ingress_security_groups = local.ingress_security_groups
      ingress_domain_name = local.ingress_domain_name
      ingress_name = local.ingress_name
      gitlab_security_groups = local.gitlab_security_groups
      gitlab_domain_name = local.gitlab_domain_name
      git_username = var.git_username
      # working_repo = var.working_repo
      ide_password = var.ide_password
      ide_password_hash = local.password_hash
      ide_password_key = local.password_key
      # backstage_image = local.backstage_image
      # backstage_postgres_secret_name = "${var.resource_prefix}-backstage-postgresql-password"
      # backstage_postgres_secret_key = "password"
    },

  )

  argocd_apps = {
    applicationsets = file("${path.module}/manifests/applicationsets.yaml")
  }
  role_arns = []
  # # Generate dynamic access entries for each admin rolelocals {
  admin_access_entries = {
    for role_arn in local.role_arns : role_arn => {
      principal_arn = role_arn
      policy_associations = {
        admins = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
  }

  # Merging dynamic entries with static entries if needed
  access_entries = merge({}, local.admin_access_entries)
}
