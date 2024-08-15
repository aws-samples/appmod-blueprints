terraform {
  required_version = ">= 1.3.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.0.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.eks_cluster.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.eks_cluster.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.eks_cluster_auth.token
}

data "aws_eks_cluster" "eks_cluster" {
  name = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "eks_cluster_auth" {
  name = var.eks_cluster_name
}

resource "kubernetes_namespace" "namespace" {
  metadata {
    name = var.namespace
  }
}

data "tls_certificate" "eks" {

  url = data.aws_eks_cluster.eks_cluster.identity[0].oidc[0].issuer

}


resource "aws_iam_openid_connect_provider" "eks" {

  client_id_list = ["sts.amazonaws.com"]

  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]

  url = data.aws_eks_cluster.eks_cluster.identity[0].oidc[0].issuer

}

resource "aws_iam_role" "service_account_role" {

  name = "eks-service-account-role"


  assume_role_policy = <<POLICY
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Federated": "${aws_iam_openid_connect_provider.eks.arn}"
        },
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {
          "StringEquals": {
            "${aws_iam_openid_connect_provider.eks.url}:sub": "system:serviceaccount:${var.namespace}:${var.service_account_name}"
          }
        }
      }
    ]
  }
  POLICY

}

resource "aws_iam_role_policy_attachment" "attach_policy" {

  for_each = toset(var.iam_policies)
  role     = aws_iam_role.service_account_role.name

  policy_arn = "arn:aws:iam::aws:policy/${each.key}"

}

resource "kubernetes_service_account" "service_account" {

  metadata {

    name = var.service_account_name

    namespace = var.namespace

    annotations = {

      "eks.amazonaws.com/role-arn" = aws_iam_role.service_account_role.arn

    }

  }

  depends_on = [

    aws_iam_role.service_account_role

  ]

}
