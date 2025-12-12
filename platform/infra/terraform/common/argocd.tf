################################################################################
# GitOps Bridge: Bootstrap
################################################################################
# Creating Namespace for better cleanup of ArgoCD helm release
# resource "kubernetes_namespace" "argocd" {
#   metadata {
#     name = local.argocd_namespace
#   }
# }

module "gitops_bridge_bootstrap" {
  source  = "gitops-bridge-dev/gitops-bridge/helm"
  version = "0.1.0"
  
  create  = true
  install = false  # Skip ArgoCD installation, only create cluster secret
  
  cluster = {
    cluster_name = local.hub_cluster.name
    environment  = local.hub_cluster.environment
    metadata     = local.addons_metadata[local.hub_cluster_key]
    addons       = local.addons[local.hub_cluster_key]
    server       = data.aws_eks_cluster.clusters[local.hub_cluster_key].arn
  }

  apps = local.argocd_apps
}

# ArgoCD Git Secret
resource "kubernetes_secret" "git_secrets" {
  depends_on = [
    module.gitops_bridge_bootstrap,
    gitlab_personal_access_token.workshop
  ]
  for_each = {
    git-repo-creds = {
      secret-type = "repo-creds"
      url         = "https://${local.gitlab_domain_name}/${local.git_username}"
      type        = "git"
      username    = "not-used"
      password    = local.gitlab_token
    }
    git-repository = {
      secret-type = "repository"
      url         = "https://${local.gitlab_domain_name}/${local.git_username}/${var.working_repo}.git"
      type        = "git"
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
