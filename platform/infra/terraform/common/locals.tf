locals {

  context_prefix = var.resource_prefix

  tags = {
    Blueprint  = local.context_prefix
    GithubRepo = "github.com/aws-samples/appmod-blueprints"
  }

}

locals {
  azs                       = slice(data.aws_availability_zones.available.names, 0, 2)
  region                    = data.aws_region.current.id
  fleet_member              = "control-plane"
  tenant                    = var.tenant
  hub_cluster_key           = [for k, v in var.clusters : k if v.environment == "control-plane"][0]
  hub_cluster               = [for k, v in var.clusters : v if v.environment == "control-plane"][0]
  hub_vpc_cidr              = data.aws_vpc.hub_cluster_vpc.cidr_block
  hub_subnet_ids            = data.aws_eks_cluster.clusters[local.hub_cluster_key].vpc_config[0].subnet_ids
  spoke_clusters            = { for k, v in var.clusters : k => v if v.environment != "control-plane" }
  cluster_vpc_ids           = { for k, v in var.clusters : v.name => data.aws_eks_cluster.clusters[k].vpc_config[0].vpc_id }
  argocd_namespace          = "argocd"
  ingress_name              = { for k, v in var.clusters : v.name => "${v.name}-ingress" }
  ingress_security_groups   = { for k, v in var.clusters : v.name => "${aws_security_group.ingress_http[k].id},${aws_security_group.ingress_https[k].id}" }
  gitlab_security_groups    = var.gitlab_security_groups
  ingress_nlb_domain_name   = "${data.aws_lb.ingress_nginx.dns_name}"
  ingress_domain_name       = aws_cloudfront_distribution.ingress.domain_name
  gitlab_domain_name        = var.gitlab_domain_name
  git_username              = var.git_username
  keycloak_realm            = "platform"
  keycloak_saml_url         = "http://${local.ingress_domain_name}/keycloak/realms/${local.keycloak_realm}/protocol/saml/descriptor"
  # git_hostname              = var.repo == "" ? "${local.gitlab_domain_name}" : var.git_hostname
  backstage_image           = var.backstage_image == "" ? "${data.aws_caller_identity.current.account_id}.dkr.ecr.${local.region}.amazonaws.com/${var.resource_prefix}-backstage:latest" : var.backstage_image
  gitops_addons_repo_url    = local.gitlab_domain_name != "" ? "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url
  gitops_fleet_repo_url       = local.gitlab_domain_name != "" ? "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url
  gitops_workload_repo_url  = local.gitlab_domain_name != "" ? "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url
  gitops_platform_repo_url  = local.gitlab_domain_name != "" ? "https://${local.gitlab_domain_name}/${var.git_username}/platform-on-eks-workshop.git" : var.repo.url

  external_secrets = {
    namespace       = "external-secrets"
    service_account = "external-secrets-sa"
    namespace_fleet = "argocd"
  }

  keycloak = {
    namespace       = "keycloak"
    service_account = "keycloak-config"
  }

  cloudwatch = {
    namespace       = "amazon-cloudwatch"
    service_account = "cloudwatch-agent"
  }

  kyverno = {
    namespace       = "kyverno"
    service_account = "policy-reporter"
  }
  aws_load_balancer_controller = {
    namespace       = "kube-system"
    service_account = "aws-load-balancer-controller-sa"
  }

  ebs_csi_controller = {
    namespace       = "kube-system"
    service_account = "ebs-csi-controller-sa"
  }

  cni_metric_helper = {
    namespace       = "kube-system"
    service_account = "cni-metrics-helper"
  }

  kargo = {
    namespace       = "kargo"
    service_account = "kargo-controller"
  }

  # karpenter = {
  #   namespace       = "kube-system"
  #   service_account = "karpenter"
  #   role_name       = "karpenter-${terraform.workspace}"
  # }

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

  adot_collector = {
    namespace = "adot-collector-kubeprometheus"
    service_account = "adot-collector-kubeprometheus"
  }

  aws_addons = {
    for k, v in var.clusters : k => v.addons
  }
  oss_addons = {
    for k, v in var.clusters : k => v.addons
  }
  
  addons = {
    for k, v in var.clusters : k => merge(
      local.aws_addons[k],
      local.oss_addons[k],
      { aws_cluster_name = v.name },
      { fleet_member = v.environment },
      { tenant = v.tenant },
      { environment = v.environment },
    )
  }

  addons_metadata = {
    for k, v in var.clusters : k => merge(
      {
        aws_cluster_name = v.name
        aws_region       = v.region
        aws_account_id   = data.aws_caller_identity.current.account_id
        aws_vpc_id       = local.cluster_vpc_ids[v.name]
        aws_grafana_url  = module.managed_grafana.workspace_endpoint
        resource_prefix  = var.resource_prefix
      },
      {
        argocd_namespace        = local.argocd_namespace,
        create_argocd_namespace = false,
        argocd_hub_role_arn = aws_iam_role.argocd_central.arn
      },
      {
        addons_repo_url      = local.gitops_addons_repo_url
        addons_repo_path     = var.gitops_addons_repo_path
        addons_repo_basepath = var.gitops_addons_repo_base_path
        addons_repo_revision = var.gitops_addons_repo_revision
      },
      {
        workload_repo_url      = local.gitops_workload_repo_url
        workload_repo_path     = var.gitops_workload_repo_path
        workload_repo_basepath = var.gitops_workload_repo_base_path
        workload_repo_revision = var.gitops_workload_repo_revision
      },
      {
        fleet_repo_url      = local.gitops_fleet_repo_url
        fleet_repo_path     = var.gitops_fleet_repo_path
        fleet_repo_basepath = var.gitops_fleet_repo_base_path
        fleet_repo_revision = var.gitops_fleet_repo_revision
      },
      {
        platform_repo_url      = local.gitops_platform_repo_url
        platform_repo_path     = var.gitops_platform_repo_path
        platform_repo_basepath = var.gitops_platform_repo_base_path
        platform_repo_revision = var.gitops_fleet_repo_revision
      },
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
        ingress_security_groups = local.ingress_security_groups[v.name]
        ingress_domain_name = local.ingress_domain_name
        ingress_name = local.ingress_name[v.name]
        gitlab_security_groups = local.gitlab_security_groups
        gitlab_domain_name = local.gitlab_domain_name
        git_username = var.git_username
        working_repo = var.working_repo
        ide_password = var.ide_password # TODO: remove this and use External Secret instead
        backstage_image = local.backstage_image
      },
    )
  }

  argocd_apps = {
    applicationsets = file("${path.module}/manifests/applicationsets.yaml")
  }
}
