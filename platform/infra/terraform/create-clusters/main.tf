terraform {
  required_version = ">= 1.3.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}


data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "codebuild_role" {
  name               = "${var.codebuild_project_name}-codebuild-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}
# CodeBuild project resource

resource "aws_codebuild_project" "eks_install_script_project" {

  name         = var.codebuild_project_name
  description  = "CodeBuild project for EKS install script"
  service_role = aws_iam_role.codebuild_role.arn

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    privileged_mode             = true
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "TF_VAR_aws_region"
      value = var.aws_region
    }
    environment_variable {
      name  = "TF_VAR_dev_cluster_name"
      value = var.dev_cluster_name
    }
    environment_variable {
      name  = "TF_VAR_prod_cluster_name"
      value = var.prod_cluster_name
    }

    environment_variable {
      name  = "GITEA_URL"
      value = var.mngmt_cluster_gitea_url
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec.yml")
  }
}


resource "aws_iam_role_policy_attachment" "codebuild_policy_attachment" {
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess" # Replace with the desired policy ARN
  role       = aws_iam_role.codebuild_role.name
}
