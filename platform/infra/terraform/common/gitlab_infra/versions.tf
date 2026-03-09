terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.23.0, <= 6.34.0"
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
      version = ">= 2.0"
    }
  }
  # Backend configuration provided via CLI parameters
  backend "s3" {
    # bucket and provided via -backend-config
    key = "gitlabinfra/terraform.tfstate"
    use_lockfile = true
  }
}
