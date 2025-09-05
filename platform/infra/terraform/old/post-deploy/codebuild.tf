# IAM service role for codebuild

data "aws_iam_role" "workshop-role" {
  name = "developer-env-VSCodeInstanceRole"
}

# CodeBuild project resource

resource "aws_codebuild_project" "eks_install_script_project" {

  name         = var.codebuild_project_name
  description  = "CodeBuild project for EKS install script"
  service_role = data.aws_iam_role.workshop-role.arn

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
      value = var.mgmt_cluster_gitea_url
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec.yml")
  }
}