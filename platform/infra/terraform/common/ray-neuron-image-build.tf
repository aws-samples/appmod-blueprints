# Terraform configuration for Ray+Neuron custom image build

# ECR Repository for Neuron Ray image
resource "aws_ecr_repository" "ray_neuron" {
  name                 = "${var.resource_prefix}-ray-neuron-custom"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "${var.resource_prefix}-ray-neuron-custom"
    Environment = "platform"
    ManagedBy   = "terraform"
  }
}

# ECR Lifecycle Policy
resource "aws_ecr_lifecycle_policy" "ray_neuron" {
  repository = aws_ecr_repository.ray_neuron.name

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
      }
    ]
  })
}

# CodeBuild Project for Neuron
resource "aws_codebuild_project" "ray_neuron" {
  name          = "${var.resource_prefix}-ray-neuron-build"
  description   = "Build custom Ray+Neuron image"
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
      value = aws_ecr_repository.ray_neuron.name
    }

    environment_variable {
      name  = "IMAGE_TAG"
      value = "latest"
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
            - aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com
            - REPOSITORY_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/$IMAGE_REPO_NAME
            - echo Creating Dockerfile...
            - |
              cat > Dockerfile << 'DOCKERFILE_EOF'
              ${indent(14, file("${path.module}/Dockerfile.ray-neuron"))}
              DOCKERFILE_EOF
        build:
          commands:
            - echo Build started on `date`
            - docker build -t $REPOSITORY_URI:$IMAGE_TAG .
        post_build:
          commands:
            - echo Pushing image...
            - docker push $REPOSITORY_URI:$IMAGE_TAG
            - echo Image pushed successfully
    EOF
  }

  tags = {
    Name        = "${var.resource_prefix}-ray-neuron-build"
    Environment = "platform"
  }
}

# Lambda to trigger Neuron build
resource "aws_lambda_function" "trigger_neuron_build" {
  filename         = data.archive_file.lambda_trigger.output_path
  function_name    = "${var.resource_prefix}-trigger-ray-neuron-build"
  role             = aws_iam_role.lambda_trigger.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  timeout          = 60
  source_code_hash = data.archive_file.lambda_trigger.output_base64sha256

  environment {
    variables = {
      CODEBUILD_PROJECT_NAME = aws_codebuild_project.ray_neuron.name
    }
  }

  tags = {
    Name = "${var.resource_prefix}-trigger-ray-neuron-build"
  }
}

# Trigger initial Neuron build
resource "null_resource" "trigger_neuron_build" {
  depends_on = [
    aws_codebuild_project.ray_neuron,
    aws_lambda_function.trigger_neuron_build
  ]

  provisioner "local-exec" {
    command = "aws lambda invoke --function-name ${aws_lambda_function.trigger_neuron_build.function_name} --region ${data.aws_region.current.name} /tmp/lambda-neuron-response.json"
  }

  triggers = {
    dockerfile_hash = filemd5("${path.module}/Dockerfile.ray-neuron")
  }
}

# Outputs
output "ray_neuron_ecr_repository_url" {
  description = "ECR repository URL for Ray+Neuron custom image"
  value       = aws_ecr_repository.ray_neuron.repository_url
}

output "ray_neuron_image_uri" {
  description = "Full image URI for Ray+Neuron custom image"
  value       = "${aws_ecr_repository.ray_neuron.repository_url}:latest"
}
