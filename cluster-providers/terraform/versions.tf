terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.25"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 3.0"
    }
    kubectl = {
      source  = "alekc/kubectl"
      version = ">= 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

provider "helm" {
  kubernetes = {
    host                   = aws_eks_cluster.hub.endpoint
    cluster_ca_certificate = base64decode(aws_eks_cluster.hub.certificate_authority[0].data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.hub.name, "--region", var.aws_region]
    }
  }
}

provider "kubectl" {
  host                   = aws_eks_cluster.hub.endpoint
  cluster_ca_certificate = base64decode(aws_eks_cluster.hub.certificate_authority[0].data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.hub.name, "--region", var.aws_region]
  }
  load_config_file = false
}
