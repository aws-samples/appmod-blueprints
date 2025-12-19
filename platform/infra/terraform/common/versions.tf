terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 4.67.0, < 6.0.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.10.1, < 3.0.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.36.0, < 3.0.0"
    }
    kubectl = {
      source  = "alekc/kubectl"
      version = ">= 2.1.3"
    }
    gitlab = {
      source = "gitlabhq/gitlab"
      version = "18.3.0"
    }
  }
  # Backend configuration provided via CLI parameters
  backend "s3" {
    # bucket provided via -backend-config
    key = "common/terraform.tfstate"
    use_lockfile = true
  }
}
