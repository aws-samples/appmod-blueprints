################################################################################
# GitOps Bridge: Private ssh keys for git
################################################################################
resource "kubernetes_namespace" "argocd" {
  depends_on = [
    local.cluster_info
  ]

  metadata {
    name = local.argocd_namespace
  }
}

# Generate password key using external data source
data "external" "password_key" {
  program = ["bash", "-c", "echo '{\"result\":\"'$(openssl rand -base64 48 | tr -d \"=+/\" | head -c 32 | base64)'\"}'"]
}

# Store both hash and key in a single file to avoid regenerating on each run
locals {
  password_file = "${path.module}/argocd-password-hash.txt"

  # Check if file exists and parse its content
  existing_data = fileexists(local.password_file) ? jsondecode(file(local.password_file)) : { hash = "", key = "" }

  # Use existing values if available, otherwise generate new ones
  password_hash = local.existing_data.hash != "" ? local.existing_data.hash : bcrypt(data.external.env_vars.result.IDE_PASSWORD)
  password_key = local.existing_data.key != "" ? local.existing_data.key : data.external.password_key.result.result
}

# Create the file with both hash and key
resource "local_file" "argocd_password_data" {
  content  = jsonencode({
    hash = local.password_hash
    key = local.password_key
  })
  filename = local.password_file

  # Only update the file if it doesn't exist or is empty
  lifecycle {
    ignore_changes = [content]
  }
}

resource "kubernetes_secret" "git_secrets" {
  depends_on = [kubernetes_namespace.argocd]
  for_each = {
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
    namespace = kubernetes_namespace.argocd.metadata[0].name
    labels = {
      "argocd.argoproj.io/secret-type" = "repository"
    }
  }
  data = each.value
}



# Create IDE password secret in ArgoCD namespace
resource "kubernetes_secret" "ide_password" {
  depends_on = [kubernetes_namespace.argocd]

  metadata {
    name      = "ide-password"
    namespace = "argocd"
  }

  data = {
    password = data.external.env_vars.result.IDE_PASSWORD
  }
}

# Create Git credentials secret in ArgoCD namespace
resource "kubernetes_secret" "git_credentials" {
  depends_on = [kubernetes_namespace.argocd]

  metadata {
    name      = "git-credentials"
    namespace = "argocd"
  }

  data = {
    GIT_HOSTNAME = "${local.git_hostname}"
    GIT_USERNAME = "${var.git_org_name}"
    GIT_PASSWORD = data.external.env_vars.result.IDE_PASSWORD
    WORKING_REPO = data.external.env_vars.result.WORKING_REPO
  }
}

################################################################################
# GitOps Bridge: Bootstrap
################################################################################
module "gitops_bridge_bootstrap" {
  source  = "gitops-bridge-dev/gitops-bridge/helm"
  version = "0.1.0"
  cluster = {
    cluster_name = module.eks.cluster_name
    environment  = local.environment
    metadata     = local.addons_metadata
    addons       = local.addons
  }

  apps = local.argocd_apps
  argocd = {
    name             = "argocd"
    namespace        = local.argocd_namespace
    chart_version    = "7.9.1"
    values           = [
      templatefile("${path.module}/argocd-initial-values.yaml", {
        DOMAIN_NAME = local.ingress_domain_name
        ADMIN_PASSWORD = local.password_hash
      })
    ]
    timeout          = 600
    create_namespace = false
  }
  depends_on = [kubernetes_secret.git_secrets]
}

################################################################################
# ArgoCD NLB Ingress
################################################################################
resource "kubernetes_ingress_v1" "argocd_nlb" {
  depends_on = [module.gitops_bridge_bootstrap]

  metadata {
    name      = "argocd-nlb"
    namespace = local.argocd_namespace
    annotations = {
      "kubernetes.io/ingress.class" = "nginx"
    }
  }

  spec {
    ingress_class_name = "nginx"
    rule {
      host = local.ingress_nlb_domain_name
      http {
        path {
          path      = "/argocd"
          path_type = "Prefix"

          backend {
            service {
              name = "argocd-server"
              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }
}

# Output the ArgoCD URL and login credentials
output "argocd_access" {
  description = "ArgoCD access information"
  value       = "ArgoCD URL: https://${local.ingress_domain_name}/argocd\nLogin: admin\nPassword: ${data.external.env_vars.result.IDE_PASSWORD}"
}
