# Terraform configuration for Ray+vLLM custom image build

# ECR Repository for custom Ray image
resource "aws_ecr_repository" "ray_vllm" {
  name                 = "${var.resource_prefix}-ray-vllm-custom"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "${var.resource_prefix}-ray-vllm-custom"
    Environment = "platform"
    ManagedBy   = "terraform"
  }
}

# ECR Lifecycle Policy
resource "aws_ecr_lifecycle_policy" "ray_vllm" {
  repository = aws_ecr_repository.ray_vllm.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "latest"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Delete untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# IAM Role for CodeBuild
resource "aws_iam_role" "codebuild_ray" {
  name = "${var.resource_prefix}-codebuild-ray-vllm"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "codebuild.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.resource_prefix}-codebuild-ray-vllm"
  }
}

# IAM Policy for CodeBuild
resource "aws_iam_role_policy" "codebuild_ray" {
  name = "${var.resource_prefix}-codebuild-ray-vllm-policy"
  role = aws_iam_role.codebuild_ray.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/codebuild/${var.resource_prefix}-ray-vllm-build*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = "*"
      }
    ]
  })
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "codebuild_ray" {
  name              = "/aws/codebuild/${var.resource_prefix}-ray-vllm-build"
  retention_in_days = 7

  tags = {
    Name = "${var.resource_prefix}-codebuild-ray-vllm-logs"
  }
}

# CodeBuild Project
resource "aws_codebuild_project" "ray_vllm" {
  name          = "${var.resource_prefix}-ray-vllm-build"
  description   = "Build custom Ray+vLLM image"
  service_role  = aws_iam_role.codebuild_ray.arn
  build_timeout = 60

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_LARGE"
    image                       = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type                        = "LINUX_CONTAINER"
    privileged_mode             = true
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = data.aws_region.current.name
    }

    environment_variable {
      name  = "AWS_ACCOUNT_ID"
      value = data.aws_caller_identity.current.account_id
    }

    environment_variable {
      name  = "IMAGE_REPO_NAME"
      value = aws_ecr_repository.ray_vllm.name
    }

    environment_variable {
      name  = "IMAGE_TAG"
      value = "latest"
    }

    environment_variable {
      name  = "CONTAINERD_ADDRESS"
      value = "/var/run/docker/containerd/containerd.sock"
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild_ray.name
    }
  }

  cache {
    type  = "LOCAL"
    modes = ["LOCAL_DOCKER_LAYER_CACHE"]
  }

  source {
    type      = "NO_SOURCE"
    buildspec = <<-EOF
      version: 0.2
      phases:
        pre_build:
          commands:
            - echo Logging in to Amazon ECR...
            - export PASSWORD=$(aws ecr get-login-password --region $AWS_DEFAULT_REGION)
            - echo $PASSWORD | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com
            - REPOSITORY_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/$IMAGE_REPO_NAME
            - COMMIT_HASH=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c 1-7)
            - IMAGE_TAG_COMMIT=$${COMMIT_HASH:-latest}
            - echo Installing SOCI CLI...
            - wget -q https://github.com/awslabs/soci-snapshotter/releases/download/v0.8.0/soci-snapshotter-0.8.0-linux-amd64.tar.gz
            - tar -xzf soci-snapshotter-0.8.0-linux-amd64.tar.gz
            - mv soci /usr/local/bin/
            - echo Creating Dockerfile...
            - |
              cat > Dockerfile << 'DOCKERFILE_EOF'
              ${indent(14, file("${path.module}/Dockerfile.ray-vllm"))}
              DOCKERFILE_EOF
        build:
          commands:
            - echo Build started on `date`
            - echo Building as OCI image...
            - docker buildx create --driver=docker-container --use
            - docker buildx build --tag $REPOSITORY_URI:$IMAGE_TAG --output type=oci,dest=./image.tar .
            - echo Importing to containerd...
            - ctr image import ./image.tar
        post_build:
          commands:
            - echo Creating SOCI index...
            - soci create $REPOSITORY_URI:$IMAGE_TAG
            - echo Pushing image and SOCI index...
            - ctr image push --user AWS:$PASSWORD $REPOSITORY_URI:$IMAGE_TAG
            - soci push --user AWS:$PASSWORD $REPOSITORY_URI:$IMAGE_TAG
            - echo Tagging commit version...
            - if [ "$IMAGE_TAG" != "$IMAGE_TAG_COMMIT" ]; then ctr image tag $REPOSITORY_URI:$IMAGE_TAG $REPOSITORY_URI:$IMAGE_TAG_COMMIT && ctr image push --user AWS:$PASSWORD $REPOSITORY_URI:$IMAGE_TAG_COMMIT; fi
            - echo Image and SOCI index pushed successfully
    EOF
  }

  tags = {
    Name        = "${var.resource_prefix}-ray-vllm-build"
    Environment = "platform"
  }
}

# Lambda function to trigger CodeBuild
data "archive_file" "lambda_trigger" {
  type        = "zip"
  output_path = "${path.module}/trigger_codebuild.zip"

  source {
    content  = <<-EOF
      import boto3
      import os
      
      codebuild = boto3.client('codebuild')
      
      def handler(event, context):
          project_name = os.environ['CODEBUILD_PROJECT_NAME']
          
          response = codebuild.start_build(projectName=project_name)
          
          return {
              'statusCode': 200,
              'body': f"Build started: {response['build']['id']}"
          }
    EOF
    filename = "index.py"
  }
}

resource "aws_lambda_function" "trigger_codebuild" {
  filename         = data.archive_file.lambda_trigger.output_path
  function_name    = "${var.resource_prefix}-trigger-ray-vllm-build"
  role             = aws_iam_role.lambda_trigger.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  timeout          = 60
  source_code_hash = data.archive_file.lambda_trigger.output_base64sha256

  environment {
    variables = {
      CODEBUILD_PROJECT_NAME = aws_codebuild_project.ray_vllm.name
    }
  }

  tags = {
    Name = "${var.resource_prefix}-trigger-ray-vllm-build"
  }
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_trigger" {
  name = "${var.resource_prefix}-lambda-trigger-codebuild"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_trigger" {
  name = "${var.resource_prefix}-lambda-trigger-policy"
  role = aws_iam_role.lambda_trigger.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "codebuild:StartBuild"
        ]
        Resource = [
          aws_codebuild_project.ray_vllm.arn,
          aws_codebuild_project.ray_neuron.arn
        ]
      }
    ]
  })
}

# Trigger initial build
resource "null_resource" "trigger_initial_build" {
  depends_on = [
    aws_codebuild_project.ray_vllm,
    aws_lambda_function.trigger_codebuild
  ]

  provisioner "local-exec" {
    command = "aws lambda invoke --function-name ${aws_lambda_function.trigger_codebuild.function_name} --region ${data.aws_region.current.name} /tmp/lambda-response.json"
  }

  triggers = {
    dockerfile_hash = filemd5("${path.module}/Dockerfile.ray-vllm")
  }
}

# Outputs
output "ray_vllm_ecr_repository_url" {
  description = "ECR repository URL for Ray+vLLM custom image"
  value       = aws_ecr_repository.ray_vllm.repository_url
}

output "ray_vllm_image_uri" {
  description = "Full image URI for Ray+vLLM custom image"
  value       = "${aws_ecr_repository.ray_vllm.repository_url}:latest"
}

output "codebuild_project_name" {
  description = "CodeBuild project name for Ray+vLLM image"
  value       = aws_codebuild_project.ray_vllm.name
}
