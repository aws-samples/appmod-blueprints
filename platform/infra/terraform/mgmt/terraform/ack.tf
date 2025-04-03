module "ack_aws_provider_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.14"

  role_name_prefix = "modern-ack-controller-aws"
  role_policy_arns = {
    policy = "arn:aws:iam::aws:policy/AdministratorAccess"
  }

  assume_role_condition_test = "StringLike"
  oidc_providers = {
    main = {
      provider_arn  = data.aws_iam_openid_connect_provider.eks_oidc.arn
      namespace_service_accounts = ["ack-system:controller-ack*"]
    }
  }
  tags = var.tags
}

resource "kubectl_manifest" "application_argocd_ack" {
  depends_on = [
    kubectl_manifest.application_ack_irsa
  ]

  yaml_body = templatefile("${path.module}/templates/argocd-apps/ack.yaml", {
     GITHUB_URL = local.repo_url
     GITHUB_BRANCH = local.repo_branch
    }
  )

  provisioner "local-exec" {

    command = "kubectl wait --for=jsonpath=.status.health.status=Healthy -n argocd application/ack --timeout=900s &&  kubectl wait --for=jsonpath=.status.sync.status=Synced --timeout=900s -n argocd application/ack"

    interpreter = ["/bin/bash", "-c"]
  }
}

resource "kubectl_manifest" "application_ack_irsa" {
  depends_on = [
    kubectl_manifest.ack_system_namespace,
  ]

  yaml_body = templatefile("${path.module}/templates/manifests/ack-aws-irsa.yaml", {
      ROLE_ARN = module.ack_aws_provider_role.iam_role_arn
    }
  )
}

# create namespace ack-system
resource "kubectl_manifest" "ack_system_namespace" {
  yaml_body = <<-YAML
apiVersion: v1
kind: Namespace
metadata:
  name: ack-system

YAML
}
