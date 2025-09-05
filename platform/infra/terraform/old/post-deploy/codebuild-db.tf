# IAM service role for codebuild

data "aws_iam_role" "db-workshop-role" {
  name = "developer-env-VSCodeInstanceRole"
}

# CodeBuild project resource

resource "aws_codebuild_project" "db_install_script_project" {

  name         = var.codebuild_project_name_db_ec2
  description  = "CodeBuild project for DB Cluster install script"
  service_role = data.aws_iam_role.db-workshop-role.arn

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
      name  = "GITEA_URL"
      value = var.mgmt_cluster_gitea_url
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-db.yml")
  }
}
