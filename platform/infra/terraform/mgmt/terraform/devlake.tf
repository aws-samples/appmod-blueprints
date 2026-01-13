resource "aws_iam_policy" "external-secrets-devlake" {
  count = local.secret_count

  name_prefix = "modern-engg-external-secrets-devlake-"
  description = "For use with External Secrets Controller for DevLake"
  policy = jsonencode(
    {
      "Version" : "2012-10-17",
      "Statement" : [
        {
          "Effect" : "Allow",
          "Action" : [
            "secretsmanager:GetResourcePolicy",
            "secretsmanager:GetSecretValue",
            "secretsmanager:DescribeSecret",
            "secretsmanager:ListSecretVersionIds"
          ],
          "Resource" : [
            "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:modern-engg/devlake/*"
          ]
        }
      ]
    }
  )
}

module "external_secrets_role_devlake" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.14"
  count   = local.secret_count

  role_name_prefix = "modern-engg-external-secrets-devlake-"

  oidc_providers = {
    main = {
      provider_arn               = data.aws_iam_openid_connect_provider.eks_oidc.arn
      namespace_service_accounts = ["devlake:external-secret-devlake"]
    }
  }
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "external_secrets_role_attach_devlake" {
  count = local.secret_count

  role       = module.external_secrets_role_devlake[0].iam_role_name
  policy_arn = aws_iam_policy.external-secrets-devlake[0].arn
}

resource "kubernetes_manifest" "namespace_devlake" {
  count = local.secret_count

  manifest = {
    "apiVersion" = "v1"
    "kind"       = "Namespace"
    "metadata" = {
      "name" = "devlake"
    }
  }
}

resource "kubernetes_manifest" "serviceaccount_external_secret_devlake" {
  count = local.secret_count
  depends_on = [
    kubernetes_manifest.namespace_devlake
  ]

  manifest = {
    "apiVersion" = "v1"
    "kind"       = "ServiceAccount"
    "metadata" = {
      "annotations" = {
        "eks.amazonaws.com/role-arn" = tostring(module.external_secrets_role_devlake[0].iam_role_arn)
      }
      "name"      = "external-secret-devlake"
      "namespace" = "devlake"
    }
  }
}

resource "kubectl_manifest" "devlake_secret_store" {
  depends_on = [
    kubernetes_manifest.serviceaccount_external_secret_devlake
  ]

  yaml_body = templatefile("${path.module}/templates/manifests/devlake-secret-store.yaml", {
    REGION = local.region
    }
  )
}


resource "random_password" "devlake_encryption_secret" {
  length  = 128
  special = false
  lower   = false
  upper   = true
  numeric = false
}

resource "aws_secretsmanager_secret" "devlake_encryption_secret" {
  count = local.secret_count

  description             = "for use with modern engineering devlake installation"
  name                    = "modern-engg/devlake/encryption"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "devlake_encryption_secret" {
  count = local.secret_count

  secret_id = aws_secretsmanager_secret.devlake_encryption_secret[0].id
  secret_string = jsonencode({
    ENCRYPTION_SECRET = random_password.devlake_encryption_secret.result
  })
}

resource "kubectl_manifest" "application_argocd_devlake" {
  depends_on = [
    kubectl_manifest.devlake_secret_store,
    kubectl_manifest.application_argocd_crossplane_compositions,
    kubectl_manifest.application_argocd_crossplane_provider
  ]

  yaml_body = templatefile("${path.module}/templates/argocd-apps/devlake.yaml", {
    GITHUB_URL    = local.repo_url
    GITHUB_BRANCH = local.repo_branch
    }
  )

}
