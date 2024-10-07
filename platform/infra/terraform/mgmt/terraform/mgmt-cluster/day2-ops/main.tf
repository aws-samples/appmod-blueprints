
locals {
  repo_url              = trimsuffix(var.repo_url, "/")
  region                = var.region
  tags                  = var.tags
  cluster_name          = var.cluster_name
  secret_count          = var.enable_external_secret ? 1 : 0
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
