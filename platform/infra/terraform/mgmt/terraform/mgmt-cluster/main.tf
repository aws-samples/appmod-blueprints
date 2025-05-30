terraform {
  required_version = ">= 1.3"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.34"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.9"
    }
  }
}

provider "aws" {
  region = local.region
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    # This requires the awscli to be installed locally where Terraform is executed
    args = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      # This requires the awscli to be installed locally where Terraform is executed
      args = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
    }
  }
}

################################################################################
# Common data/locals
################################################################################

data "aws_availability_zones" "available" {}

locals {
  name   = "modern-engineering"
  region = "us-west-2"
  eks_version = "1.32"
  
  vpc_cidr = "10.0.0.0/16"
  azs      = slice(data.aws_availability_zones.available.names, 0, 3)

  tags = {
    EKSCluster  = local.name
  }
}

################################################################################
# Usage Telemetry
################################################################################

resource "aws_cloudformation_stack" "usage_tracking" {
  count = var.usage_tracking_tag != null ? 1 : 0

  name = "modern-engineering"

  on_failure = "DO_NOTHING"
  template_body = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09",
    Description              = "Usage telemetry for Modern Engineering. (${var.usage_tracking_tag})",
    Resources = {
      EmptyResource = {
        Type = "AWS::CloudFormation::WaitConditionHandle"
      }
    }
  })
}