
locals {
  repo_url              = trimsuffix(var.repo_url, "/")
  region                = var.region
  tags                  = var.tags
  cluster_name          = var.cluster_name
  secret_count          = var.enable_external_secret ? 1 : 0
  tf_integrations_count = var.enable_terraform_integrations ? 1 : 0
  aiml_integrations_count = var.enable_aiml_integrations ? 1 : 0

  domain_name           = var.domain_name
  kc_url                = "https://${local.domain_name}/keycloak/realms/modernengg"
  argo_redirect_url     = "https://${local.domain_name}/argo-workflows/oauth2/callback"
}


provider "aws" {
  region = local.region
  default_tags {
    tags = local.tags
  }
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

provider "helm" {
  kubernetes {
    config_path = "~/.kube/config"
  }
}
