################################################################################
# GitOps Bridge: Private ssh keys for git
################################################################################
# resource "kubernetes_namespace" "argocd" {
#   depends_on = [
#     local.cluster_info
#   ]

#   metadata {
#     name = local.argocd_namespace
#   }
# }



# # Create IDE password secret in ArgoCD namespace
# resource "kubernetes_secret" "ide_password" {
#   depends_on = [kubernetes_namespace.argocd]

#   metadata {
#     name      = "ide-password"
#     namespace = "argocd"
#   }

#   data = {
#     password = var.ide_password
#   }
# }

# # Create Git credentials secret in ArgoCD namespace
# resource "kubernetes_secret" "git_credentials" {
#   depends_on = [kubernetes_namespace.argocd]

#   metadata {
#     name      = "git-credentials"
#     namespace = "argocd"
#   }

#   data = {
#     GIT_HOSTNAME = "${local.git_hostname}"
#     GIT_USERNAME = "${var.git_org_name}"
#     GIT_PASSWORD = jsondecode(data.aws_secretsmanager_secret_version.keycloak_user_password.secret_string)["password"]
#     WORKING_REPO = var.working_repo
#   }
# }

################################################################################
# GitOps Bridge: Bootstrap
################################################################################
module "gitops_bridge_bootstrap" {
  source  = "gitops-bridge-dev/gitops-bridge/helm"
  version = "0.1.0"
  cluster = {
    cluster_name = local.hub_cluster.name
    environment  = local.hub_cluster.environment
    metadata     = local.addons_metadata[local.hub_cluster_key]
    addons       = local.addons[local.hub_cluster_key]
  }

  apps = local.argocd_apps
  argocd = {
    name             = "argocd"
    namespace        = local.argocd_namespace
    chart_version    = "7.9.1"
    values           = [
      templatefile("${path.module}/manifests/argocd-initial-values.yaml", {
        DOMAIN_NAME = local.ingress_domain_name
        ADMIN_PASSWORD = local.user_password_hash
      })
    ]
    timeout          = 600
    create_namespace = false
  }
  # depends_on = [kubernetes_secret.git_secrets]
}

# ArgoCD Git Secret
resource "kubernetes_secret" "git_secrets" {
  depends_on = [
    module.gitops_bridge_bootstrap,
    gitlab_personal_access_token.workshop
    ]
  for_each = {
    git-repo-creds = {
      secret-type= "repo-creds"
      url= "https://${local.gitlab_domain_name}/${local.git_username}"
      type= "git"
      username= "not-used"
      password= local.gitlab_token
    }
    git-reposiotory = {
      secret-type= "repository"
      url= "https://${local.gitlab_domain_name}/${local.git_username}/${var.working_repo}.git"
      type= "git"
    }
    # git-addons = {
    #   type                    = "git"
    #   url                     = "https://github.com/eks-fleet-management/gitops-addons-private.git"
    #   githubAppID             = local.git_data["github_app_id"]
    #   githubAppInstallationID = local.git_data["github_app_installation_id"]
    #   githubAppPrivateKey     = base64decode(local.git_data["github_private_key"])
    # }
    # git-fleet = {
    #   type                    = "git"
    #   url                     = "https://github.com/eks-fleet-management/gitops-fleet.git"
    #   githubAppID             = local.git_data["github_app_id"]
    #   githubAppInstallationID = local.git_data["github_app_installation_id"]
    #   githubAppPrivateKey     = base64decode(local.git_data["github_private_key"])
    # }
    # git-resources = {
    #   type                    = "git"
    #   url                     = "https://github.com/eks-fleet-management/gitops-resources.git"
    #   githubAppID             = local.git_data["github_app_id"]
    #   githubAppInstallationID = local.git_data["github_app_installation_id"]
    #   githubAppPrivateKey     = base64decode(local.git_data["github_private_key"])
    # }
  }
  metadata {
    name      = each.key
    namespace = local.argocd_namespace
    labels = {
      "argocd.argoproj.io/secret-type" = "${each.value.secret-type}"
    }
  }
  data = each.value
}
# ################################################################################
# # ArgoCD NLB Ingress
# ################################################################################
# resource "kubernetes_ingress_v1" "argocd_nlb" {
#   depends_on = [module.gitops_bridge_bootstrap]

#   metadata {
#     name      = "argocd-nlb"
#     namespace = local.argocd_namespace
#     annotations = {
#       "kubernetes.io/ingress.class" = "nginx"
#     }
#   }

#   spec {
#     ingress_class_name = "nginx"
#     rule {
#       host = local.ingress_nlb_domain_name
#       http {
#         path {
#           path      = "/argocd"
#           path_type = "Prefix"

#           backend {
#             service {
#               name = "argocd-server"
#               port {
#                 number = 80
#               }
#             }
#           }
#         }
#       }
#     }
#   }
# }
