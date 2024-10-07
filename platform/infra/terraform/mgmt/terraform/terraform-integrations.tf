data "http" "flux_manifestfile" {
  count = local.tf_integrations_count
  url   = "https://raw.githubusercontent.com/cnoe-io/stacks/main/terraform-integrations/fluxcd.yaml"
}
resource "kubectl_manifest" "flux_manifest" {
  count     = local.tf_integrations_count
  yaml_body = data.http.flux_manifestfile[0].response_body
}

module "tofu_aws_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.14"

  role_name_prefix = "modern-tofu-aws"
  role_policy_arns = {
    policy = "arn:aws:iam::aws:policy/AdministratorAccess"
  }

  assume_role_condition_test = "StringLike"
  oidc_providers = {
    main = {
      provider_arn = data.aws_iam_openid_connect_provider.eks_oidc.arn
      namespace_service_accounts = ["flux-system:tf-runner"]
    }
  }
  tags = var.tags
}

resource "kubectl_manifest" "application_argocd_tofu_controller" {
  depends_on = [
    module.tofu_aws_role
  ]
  yaml_body = templatefile("${path.module}/templates/argocd-apps/tofu-controller.yaml", {
    ROLE_ARN = module.tofu_aws_role.iam_role_arn
  }
  )
}
