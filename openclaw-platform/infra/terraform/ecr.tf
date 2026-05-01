# ECR repository for the finance-assistant web UI image.
# The OpenClaw base image stays on GHCR (upstream community image); only the
# custom UI we build locally needs its own registry.

resource "aws_ecr_repository" "finance_ui" {
  name                 = "finance-ui"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = local.tags
}

resource "aws_ecr_lifecycle_policy" "finance_ui" {
  repository = aws_ecr_repository.finance_ui.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep only the 10 most recent images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      }
    ]
  })
}
